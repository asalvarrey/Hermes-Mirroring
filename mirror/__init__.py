from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Re-export clean public API
from .schema import Snapshot, Manifest, SkillEntry, PluginEntry, CredentialManifest, MemoryPolicy, DeployConfig
from .collector import Collector
from .sanitizer import Sanitizer
from .packager import Packager, build_deployment_artifact
from .deployer import Deployer, DeployError

__all__ = [
    "Snapshot", "Manifest", "SkillEntry", "PluginEntry",
    "CredentialManifest", "MemoryPolicy", "DeployConfig",
    "Collector", "Sanitizer", "Packager", "Deployer",
    "build_deployment_artifact", "DeployError",
]

# Snapshot storage directory
MIRROR_STORAGE = Path.home() / ".hermes" / "mirrors"


def list_snapshots() -> List[Dict[str, Any]]:
    """List all saved mirror snapshots with metadata."""
    if not MIRROR_STORAGE.exists():
        return []

    snapshots = []
    for item in sorted(MIRROR_STORAGE.iterdir()):
        snapshot_json = item / "snapshot.json"
        if snapshot_json.exists():
            try:
                snap = Snapshot.from_json_file(str(snapshot_json))
                has_artifacts = any(f.name.endswith((".tar.gz", ".tar")) for f in item.iterdir())
                snapshots.append({
                    "mirror_id": snap.manifest.mirror_id,
                    "created_at": snap.manifest.created_at[:19],
                    "description": snap.manifest.description,
                    "tags": snap.manifest.tags,
                    "skills": len(snap.skills),
                    "plugins": len(snap.plugins),
                    "has_artifacts": has_artifacts,
                    "path": str(item),
                })
            except Exception as e:
                snapshots.append({
                    "mirror_id": item.name,
                    "error": str(e),
                    "path": str(item),
                })
    return snapshots


def inspect_snapshot(mirror_id: str) -> Optional[Dict[str, Any]]:
    """Inspect a specific mirror snapshot in detail."""
    snap_dir = MIRROR_STORAGE / mirror_id
    snapshot_json = snap_dir / "snapshot.json"
    if not snapshot_json.exists():
        return None

    snap = Snapshot.from_json_file(str(snapshot_json))
    errors = snap.validate()

    return {
        "manifest": {
            "version": snap.manifest.version,
            "mirror_id": snap.manifest.mirror_id,
            "created_at": snap.manifest.created_at,
            "description": snap.manifest.description,
            "tags": snap.manifest.tags,
        },
        "identity": {
            "name": snap.identity.name,
            "personality": snap.identity.personality,
        },
        "skills": [
            {"name": s.name, "version": s.version, "hash": s.content_hash[:16]}
            for s in snap.skills
        ],
        "plugins": [
            {"name": p.name, "version": p.version, "enabled": p.enabled}
            for p in snap.plugins
        ],
        "config": {
            "model": snap.config.get("model", {}),
            "toolsets": snap.config.get("toolsets", []),
        },
        "credentials_required": snap.credentials.env_vars,
        "memory_included": snap.memory_snapshot.included,
        "deployment": {
            "strategy": snap.deployment.strategy,
            "port": snap.deployment.docker.get("port", 8000),
        },
        "valid": len(errors) == 0,
        "errors": errors,
    }


def delete_snapshot(mirror_id: str) -> bool:
    """Delete a mirror snapshot from disk."""
    import shutil
    snap_dir = MIRROR_STORAGE / mirror_id
    if not snap_dir.exists():
        return False
    shutil.rmtree(snap_dir)
    return True
