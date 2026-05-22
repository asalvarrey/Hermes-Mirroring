"""Hermes Mirror Plugin — Sub-Agent Mirroring Deployment

Capability: Package a specific Hermes configuration (skills, memory, plugins,
config) and deploy it as a new Docker container or VPS instance.

See mirror/schema.py for the snapshot format.
See mirror/collector.py for the collection engine.
See mirror/sanitizer.py for the PII scrubbing layer.
See mirror/packager.py for the Docker/tar artifact builder.
See mirror/deployer.py for the deployment runners.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# Re-export the public API
from .mirror.schema import Snapshot, Manifest, SkillEntry, PluginEntry
from .mirror.collector import Collector
from .mirror.sanitizer import Sanitizer
from .mirror.packager import Packager, build_deployment_artifact
from .mirror.deployer import Deployer, DeployError


# ---------------------------------------------------------------------------
# Plugin entry point — called by Hermes plugin system
# ---------------------------------------------------------------------------

__all__ = [
    "MirrorPlugin",
    "Snapshot",
    "Collector",
    "Sanitizer",
    "Packager",
    "Deployer",
    "build_deployment_artifact",
]


class MirrorPlugin:
    """Hermes Mirror Plugin — agent cloning & deployment."""

    def __init__(self):
        self._initialized = False

    def initialize(self, **kwargs) -> None:
        logger.info("Hermes Mirror Plugin initialized ✅")
        self._initialized = True

    def preview(self) -> str:
        return (
            "🪞 **Sub-Agent Mirroring Plugin**\n"
            "   `hermes mirror create` — snapshot your agent\n"
            "   `hermes mirror deploy` — deploy to Docker/VPS\n"
            "   `hermes mirror list` — view saved snapshots\n"
            "   `hermes mirror inspect <id>` — snapshot details\n"
        )

    def system_prompt_block(self) -> str:
        return (
            "You have the Mirroring Plugin enabled. "
            "You can clone, sanitize, package, and deploy yourself "
            "as a new Hermes instance with `hermes mirror create`."
        )


# ---------------------------------------------------------------------------
# Tool schemas exposed to the model
# ---------------------------------------------------------------------------

MIRROR_CREATE_SCHEMA = {
    "name": "mirror_create",
    "description": (
        "Create a self-snapshot of the current Hermes agent. "
        "Collects skills, config, plugins, and optionally memory, "
        "sanitizes PII, and produces a snapshot.json manifest. "
        "Use mirror_deploy to turn it into a running container or VPS instance."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "mirror_id": {
                "type": "string",
                "description": "Name for the mirror (e.g. 'hermes-finance-v2')",
            },
            "description": {
                "type": "string",
                "description": "Human-readable description",
            },
            "tags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Tags for organization",
            },
            "profile": {
                "type": "string",
                "enum": ["standard", "minimal", "paranoid", "devops", "minimal_plus_email"],
                "description": "Sanitization profile (default: standard)",
                "default": "standard",
            },
            "include_memory": {
                "type": "boolean",
                "description": "Include vector memory in snapshot (default: false)",
                "default": False,
            },
        },
        "required": ["mirror_id"],
    },
}

MIRROR_DEPLOY_SCHEMA = {
    "name": "mirror_deploy",
    "description": (
        "Deploy a saved mirror snapshot as a Docker container or to a VPS. "
        "Packages the snapshot into a Docker image, builds it, and runs it. "
        "Optionally supply an .env file for credential injection."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "mirror_id": {
                "type": "string",
                "description": "Name of the mirror snapshot to deploy",
            },
            "target": {
                "type": "string",
                "enum": ["docker", "vps"],
                "description": "Deployment target (default: docker)",
                "default": "docker",
            },
            "env_file": {
                "type": "string",
                "description": "Path to .env file with credentials for the new agent",
            },
            "ssh_host": {
                "type": "string",
                "description": "VPS hostname/IP (required when target=vps)",
            },
            "ssh_user": {
                "type": "string",
                "description": "VPS SSH user (default: root)",
                "default": "root",
            },
            "port": {
                "type": "integer",
                "description": "Port to expose (default: 8000)",
                "default": 8000,
            },
        },
        "required": ["mirror_id"],
    },
}

MIRROR_LIST_SCHEMA = {
    "name": "mirror_list",
    "description": "List all saved mirror snapshots with metadata.",
    "parameters": {
        "type": "object",
        "properties": {},
    },
}

MIRROR_INSPECT_SCHEMA = {
    "name": "mirror_inspect",
    "description": "Show detailed information about a saved mirror snapshot.",
    "parameters": {
        "type": "object",
        "properties": {
            "mirror_id": {
                "type": "string",
                "description": "Name of the mirror snapshot to inspect",
            },
        },
        "required": ["mirror_id"],
    },
}

MIRROR_DELETE_SCHEMA = {
    "name": "mirror_delete",
    "description": "Delete a saved mirror snapshot from disk.",
    "parameters": {
        "type": "object",
        "properties": {
            "mirror_id": {
                "type": "string",
                "description": "Name of the mirror snapshot to delete",
            },
        },
        "required": ["mirror_id"],
    },
}
