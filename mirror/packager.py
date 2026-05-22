"""Sub-Agent Mirroring — Packager

Takes a completed Snapshot and packages it into a deployable artifact:
  - Creates the snapshot.json manifest
  - Generates a Dockerfile with all skills embedded
  - Creates docker-compose.yml for orchestration
  - Generates entrypoint script that auto-configures Hermes on first run
  - Optionally creates a standalone tar.gz for VPS deployment
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import tarfile
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from .schema import Snapshot

logger = logging.getLogger(__name__)

# Template for the Dockerfile
DOCKERFILE_TEMPLATE = """# =============================================================================
# Hermes Mirror — Automated deployment image
# Source: {mirror_id}
# Created: {created_at}
# =============================================================================

FROM {base_image}

LABEL org.hermes.mirror="{mirror_id}"
LABEL org.hermes.version="{version}"

# Prevent Python from writing .pyc files
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV HERMES_HOME=/etc/hermes

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \\
    git \\
    curl \\
    ca-certificates \\
    && rm -rf /var/lib/apt/lists/*

# Install Hermes Agent
RUN pip install --no-cache-dir {hermes_install}

# Create directory structure
RUN mkdir -p $HERMES_HOME/skills $HERMES_HOME/plugins $HERMES_HOME/cache

# Copy snapshot manifest
COPY snapshot.json /etc/hermes-mirror/snapshot.json

# Copy skills
{skill_copies}

# Copy plugins (source code)
{plugin_copies}

# Copy config
COPY config.yaml $HERMES_HOME/config.yaml

# Copy entrypoint
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Persist paths for memory
VOLUME ["/etc/hermes/data"]

EXPOSE {port}

ENTRYPOINT ["/entrypoint.sh"]
CMD ["hermes"]
"""

DOCKER_COMPOSE_TEMPLATE = """# =============================================================================
# Hermes Mirror — Docker Compose
# =============================================================================
# Deploy with: docker compose up -d {service_name}
# Supply env vars via .env file or environment
# =============================================================================

version: "3.8"

services:
  {service_name}:
    build:
      context: .
      dockerfile: Dockerfile
    image: {mirror_id}:latest
    container_name: {mirror_id}
    restart: unless-stopped
    ports:
      - "{port}:{port}"
    volumes:
      # Persistent memory (survives container restarts)
      - hermes_data:/etc/hermes/data
      # Optional: mount your .env file
      - {env_mount}
    env_file:
      - {env_file_ref}
    environment:
      - HERMES_HOME=/etc/hermes
      - HERMES_MIRROR_ID={mirror_id}
    command: hermes --gateway

volumes:
  hermes_data:
"""

ENTRYPOINT_TEMPLATE = """#!/bin/bash
# =============================================================================
# Hermes Mirror Entrypoint
# =============================================================================
# On first run, this script:
#   1. Loads environment variables
#   2. Ensures snapshot skills are installed in HERMES_HOME
#   3. Starts Hermes with the mirror configuration
# =============================================================================

set -e

HERMES_HOME="${{HERMES_HOME:-/etc/hermes}}"
SNAPSHOT_DIR="/etc/hermes-mirror"
DATA_DIR="$HERMES_HOME/data"
MIRROR_ID="{mirror_id}"

mkdir -p "$DATA_DIR"

echo "[Hermes Mirror] Starting mirror: $MIRROR_ID"

# Phase 1: Ensure skills are installed
if [ -f "$SNAPSHOT_DIR/snapshot.json" ]; then
    echo "[Hermes Mirror] Installing skills from snapshot..."
    SKILLS_DIR="$HERMES_HOME/skills"
    mkdir -p "$SKILLS_DIR"
    # Skills are embedded in the image, just ensure dirs exist
fi

# Phase 2: Check env vars
if [ -z "$HERMES_API_KEY" ] && [ -z "$OPENAI_API_KEY" ]; then
    echo "[Hermes Mirror] WARNING: No API key set. Supply via .env file or HERMES_API_KEY env var."
fi

# Phase 3: Start Hermes
echo "[Hermes Mirror] Starting Hermes Agent..."
exec "$@"
"""


class Packager:
    """Package a Snapshot into deployable artifacts."""

    def __init__(self, work_dir: Optional[Path] = None):
        self.work_dir = work_dir or Path(tempfile.mkdtemp(prefix="hermes-mirror-"))
        logger.info("Packager work dir: %s", self.work_dir)

    def package_docker(self, snapshot: Snapshot) -> Path:
        """Create a Docker build context directory.

        Returns path to the build context directory.
        """
        ctx = self.work_dir / "docker"
        ctx.mkdir(parents=True, exist_ok=True)

        # 1. Write snapshot.json
        (ctx / "snapshot.json").write_text(snapshot.to_json(), encoding="utf-8")

        # 2. Write config.yaml
        self._write_config_yaml(ctx, snapshot)

        # 3. Write skills
        skills_dir = ctx / "skills"
        skills_dir.mkdir(exist_ok=True)
        skill_copies = []
        for skill_entry in snapshot.skills:
            skill_path = skills_dir / skill_entry.name
            skill_path.mkdir(exist_ok=True)
            (skill_path / "SKILL.md").write_text(skill_entry.content or "", encoding="utf-8")
            skill_copies.append(
                f"COPY skills/{skill_entry.name}/SKILL.md "
                f"$HERMES_HOME/skills/{skill_entry.name}/SKILL.md"
            )

        # 4. Write plugins
        plugins_dir = ctx / "plugins"
        plugins_dir.mkdir(exist_ok=True)
        plugin_copies = []
        for plugin_entry in snapshot.plugins:
            plugin_path = plugins_dir / plugin_entry.name
            plugin_path.mkdir(exist_ok=True)
            # Write a minimal plugin.yaml from the snapshot data
            (plugin_path / "plugin.yaml").write_text(
                json.dumps({
                    "name": plugin_entry.name,
                    "version": plugin_entry.version,
                    "config": plugin_entry.config,
                }, indent=2),
                encoding="utf-8",
            )
            plugin_copies.append(
                f"COPY plugins/{plugin_entry.name}/ $HERMES_HOME/plugins/{plugin_entry.name}/"
            )

        # 5. Write Dockerfile
        docker = snapshot.deployment.docker
        base_image = docker.get("base_image", "python:3.11-slim")
        port = docker.get("port", 8000)
        hermes_install = docker.get("hermes_install", "hermes-agent")

        dockerfile = DOCKERFILE_TEMPLATE.format(
            mirror_id=snapshot.manifest.mirror_id,
            created_at=snapshot.manifest.created_at[:10],
            version=snapshot.manifest.version,
            base_image=base_image,
            port=port,
            hermes_install=hermes_install,
            skill_copies="\n".join(skill_copies) if skill_copies else "# No skills",
            plugin_copies="\n".join(plugin_copies) if plugin_copies else "# No plugins",
        )
        (ctx / "Dockerfile").write_text(dockerfile, encoding="utf-8")

        # 6. Write entrypoint
        entrypoint = ENTRYPOINT_TEMPLATE.format(mirror_id=snapshot.manifest.mirror_id)
        (ctx / "entrypoint.sh").write_text(entrypoint, encoding="utf-8")
        (ctx / "entrypoint.sh").chmod(0o755)

        # 7. Write docker-compose.yml
        compose = DOCKER_COMPOSE_TEMPLATE.format(
            service_name=snapshot.manifest.mirror_id.replace("-", "_"),
            mirror_id=snapshot.manifest.mirror_id,
            port=port,
            env_mount="./.env:/etc/hermes/.env:ro" if docker.get("env_file_required", True) else "/dev/null:/dev/null",
            env_file_ref="./.env" if docker.get("env_file_required", True) else "/dev/null",
        )
        (ctx / "docker-compose.yml").write_text(compose, encoding="utf-8")

        logger.info("Packager: Docker context ready at %s (%d files)", ctx, len(list(ctx.rglob("*"))))
        return ctx

    def package_tar(self, snapshot: Snapshot) -> Path:
        """Create a standalone tar.gz for VPS/local deployment.

        Returns path to the .tar.gz file.
        """
        ctx = self.package_docker(snapshot)
        tar_path = self.work_dir / f"{snapshot.manifest.mirror_id}-deploy.tar.gz"

        with tarfile.open(tar_path, "w:gz") as tar:
            tar.add(ctx, arcname=snapshot.manifest.mirror_id)

        logger.info("Packager: tar.gz ready at %s (%.1f KB)",
                     tar_path, tar_path.stat().st_size / 1024)
        return tar_path

    def _write_config_yaml(self, ctx: Path, snapshot: Snapshot) -> None:
        """Generate a Hermes config.yaml from the snapshot config."""
        safe_config = {
            "model": snapshot.config.get("model", {}),
            "toolsets": snapshot.config.get("toolsets", []),
            "agent": snapshot.config.get("agent", {}),
            "memory": {"provider": "sqlite"},
        }

        import yaml
        config_text = yaml.dump(safe_config, default_flow_style=False, sort_keys=False)
        (ctx / "config.yaml").write_text(config_text, encoding="utf-8")

    def cleanup(self) -> None:
        """Remove work directory."""
        if self.work_dir and self.work_dir.exists():
            shutil.rmtree(self.work_dir)
            logger.info("Packager: cleaned up %s", self.work_dir)


# ---------------------------------------------------------------------------
# High-level convenience
# ---------------------------------------------------------------------------

def build_deployment_artifact(snapshot: Snapshot, fmt: str = "docker") -> Path:
    """One-shot: build a deployment artifact from a snapshot.

    Args:
        snapshot: The Snapshot to package.
        fmt: 'docker' (build context dir) or 'tar' (standalone tar.gz).

    Returns:
        Path to the resulting artifact.
    """
    packager = Packager()
    try:
        if fmt == "tar":
            return packager.package_tar(snapshot)
        return packager.package_docker(snapshot)
    except Exception:
        packager.cleanup()
        raise
