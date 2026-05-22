"""Sub-Agent Mirroring — Deployer

Takes a packaged snapshot artifact and deploys it to:
  - Local Docker (docker build + docker run)
  - Remote VPS (scp + ssh + docker-compose up)
  - Docker Compose stack (docker compose up -d)
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .schema import Snapshot

logger = logging.getLogger(__name__)


class DeployError(Exception):
    """Raised when deployment fails."""
    pass


class Deployer:
    """Deploy a snapshot to Docker or VPS."""

    def __init__(self, env_file: Optional[Path] = None, verbose: bool = False):
        self.env_file = env_file
        self.verbose = verbose

    # ------------------------------------------------------------------
    # Docker — local
    # ------------------------------------------------------------------

    def deploy_docker(self, build_context: Path, snapshot: Snapshot,
                      tag: str = "", detach: bool = True) -> Dict[str, Any]:
        """Build and run a Docker container from a build context.

        Args:
            build_context: Path to the Docker build context (from Packager).
            snapshot: The Snapshot being deployed.
            tag: Optional image tag (defaults to mirror_id).
            detach: Run in background (default True).

        Returns:
            Dict with container_id, image_tag, port, status.
        """
        tag = tag or snapshot.manifest.mirror_id
        port = snapshot.deployment.docker.get("port", 8000)

        # 1. Build
        logger.info("Deployer: building Docker image '%s' from %s", tag, build_context)
        build_cmd = ["docker", "build", "-t", tag, str(build_context)]
        self._run(build_cmd, cwd=build_context)

        # 2. Run
        docker_args: List[str] = ["docker", "run"]

        if detach:
            docker_args.append("-d")

        docker_args.extend(["-p", f"{port}:{port}", "--name", tag])

        if self.env_file and self.env_file.exists():
            docker_args.extend(["--env-file", str(self.env_file.absolute())])

        docker_args.append(tag)

        logger.info("Deployer: starting container: %s", " ".join(docker_args))
        result = self._run(docker_args)

        container_id = result.strip()
        logger.info("Deployer: container started: %s", container_id)

        return {
            "container_id": container_id,
            "image_tag": tag,
            "port": port,
            "status": "running" if detach else "attached",
        }

    def deploy_docker_compose(self, build_context: Path, snapshot: Snapshot,
                              detach: bool = True) -> Dict[str, Any]:
        """Deploy using docker-compose from the build context."""
        service_name = snapshot.manifest.mirror_id.replace("-", "_")

        cmd = ["docker", "compose"]

        if detach:
            cmd.append("-d")

        cmd.extend(["-f", str(build_context / "docker-compose.yml"), "up", "--build"])

        if detach:
            cmd.extend(["-d"])

        logger.info("Deployer: docker compose up for '%s'", service_name)
        self._run(cmd, cwd=build_context)

        # Verify
        inspect = self._run(["docker", "compose", "-f",
                             str(build_context / "docker-compose.yml"),
                             "ps", "--format", "json"], cwd=build_context)
        try:
            status = json.loads(inspect) if inspect.strip() else {}
        except json.JSONDecodeError:
            status = {"status": "unknown"}

        return {
            "service": service_name,
            "status": status,
        }

    # ------------------------------------------------------------------
    # VPS — remote
    # ------------------------------------------------------------------

    def deploy_vps(self, tar_path: Path, snapshot: Snapshot,
                   ssh_host: str, ssh_user: str = "root",
                   install_dir: str = "/opt/hermes-mirror") -> Dict[str, Any]:
        """Deploy a tar.gz artifact to a remote VPS via SSH.

        Flow:
          1. scp the tar.gz to the server
          2. ssh to extract, docker-compose up
        """
        if not shutil_available():
            raise DeployError("shutil/scp not available for VPS deploy")

        remote_path = f"{ssh_user}@{ssh_host}:{install_dir}/"
        docker_compose_dir = f"{install_dir}/{snapshot.manifest.mirror_id}"

        # 1. Create remote dir & copy artifact
        self._run(["ssh", f"{ssh_user}@{ssh_host}", f"mkdir -p {install_dir}"])
        self._run(["scp", str(tar_path), remote_path])

        # 2. Extract on remote
        self._run([
            "ssh", f"{ssh_user}@{ssh_host}",
            f"cd {install_dir} && tar xzf {tar_path.name} && "
            f"cd {snapshot.manifest.mirror_id} && "
            f"docker compose up -d --build",
        ])

        logger.info("Deployer: VPS deploy complete: %s -> %s", tar_path.name, ssh_host)

        return {
            "ssh_host": ssh_host,
            "install_dir": install_dir,
            "status": "deployed",
        }

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    def _run(self, cmd: List[str], cwd: Optional[Path] = None) -> str:
        """Run a command and return stdout. Raises DeployError on failure."""
        logger.debug("Deployer: running: %s", " ".join(cmd))
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=str(cwd) if cwd else None,
                timeout=300,
            )
            if result.returncode != 0:
                raise DeployError(
                    f"Command failed (exit {result.returncode}): {' '.join(cmd)}\n"
                    f"stderr: {result.stderr.strip()}"
                )
            return result.stdout.strip()
        except FileNotFoundError as e:
            raise DeployError(f"Command not found: {e}")

    def verify_health(self, container_id: str, timeout: int = 30) -> bool:
        """Poll docker logs until Hermes starts or timeout."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            logs = self._run(["docker", "logs", container_id, "--tail", "5"])
            if "Hermes Mirror" in logs or "Starting" in logs:
                return True
            time.sleep(2)
        return False


def shutil_available() -> bool:
    """Check if scp/ssh are available."""
    for cmd in ["scp", "ssh"]:
        if subprocess.run(["which", cmd], capture_output=True, text=True).returncode != 0:
            return False
    return True
