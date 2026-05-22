"""Sub-Agent Mirroring — Snapshot Schema Definition

Defines the canonical JSON schema for a Hermes mirror snapshot.
Every snapshot is a self-contained description of everything needed
to spawn a clone of the original agent.

Typical snapshot.json:

{
  "manifest": {
    "version": "1.0.0",
    "created_at": "2026-05-22T23:00:00Z",
    "original_id": "hermes-default",
    "mirror_id": "hermes-finance-v2",
    "description": "Financial analysis agent clone",
    "tags": ["finance", "analyst", "production"]
  },
  "identity": {
    "name": "Hermes Finance",
    "personality": "analytical, concise, data-driven",
    "system_prompt_extra": "You are a financial analyst assistant..."
  },
  "skills": [
    {
      "name": "youtube-content",
      "version": "1.2.0",
      "content_hash": "sha256:abc123...",
      "content": "SKILL.md content or path"
    }
  ],
  "config": {
    "model": { "default": "deepseek/deepseek-v4-flash", "provider": "nous" },
    "toolsets": ["hermes-cli", "web", "terminal"],
    "agent": { "max_turns": 90 }
  },
  "credentials": {
    "env_vars": ["SUPABASE_URL", "SUPABASE_ANON_KEY"],
    "values_placeholder": true,
    "notes": "Credentials are NOT included. Supply via --env-file or interactively."
  },
  "memory_snapshot": {
    "included": false,
    "size_bytes": 0,
    "entries": 0,
    "filter_policy": "none"
  },
  "plugins": [
    {
      "name": "supabase",
      "version": "1.0.1",
      "enabled": true,
      "content_hash": "sha256:def456..."
    }
  ],
  "dependencies": {
    "python_packages": ["supabase>=2.0.0"],
    "system_packages": ["docker-ce"],
    "hermes_version": ">=2.0.0"
  },
  "deployment": {
    "strategy": "docker",
    "docker": {
      "base_image": "python:3.11-slim",
      "port": 8000,
      "env_file_required": true
    },
    "vps": {
      "ssh_user": "root",
      "ssh_host": "",
      "install_dir": "/opt/hermes-mirror"
    }
  }
}
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Schema constants
# ---------------------------------------------------------------------------

MIRROR_SCHEMA_VERSION = "1.0.0"

# Fields that MUST be present in a valid snapshot
REQUIRED_TOP_LEVEL = {"manifest", "skills", "config", "dependencies"}

# Fields that are NEVER included in exported snapshots (sanitized away)
BLOCKED_IDENTITY_FIELDS = {"user_id", "original_session_id", "discord_id",
                           "telegram_id", "phone_number", "email"}

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class Manifest:
    version: str = MIRROR_SCHEMA_VERSION
    created_at: str = ""
    original_id: str = ""
    mirror_id: str = ""
    description: str = ""
    tags: List[str] = field(default_factory=list)


@dataclass
class Identity:
    name: str = "Hermes Mirror"
    personality: str = ""
    system_prompt_extra: str = ""


@dataclass
class SkillEntry:
    name: str = ""
    version: str = ""
    content_hash: str = ""  # sha256 of the SKILL.md
    content: str = ""       # Base64 or path reference; "" = fetch at deploy time


@dataclass
class PluginEntry:
    name: str = ""
    version: str = ""
    enabled: bool = True
    content_hash: str = ""
    config: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CredentialManifest:
    env_vars: List[str] = field(default_factory=list)
    values_placeholder: bool = True  # True = ask user at deploy
    notes: str = "Credentials supplied via --env-file or interactive prompt."


@dataclass
class MemoryPolicy:
    included: bool = False
    size_bytes: int = 0
    entries: int = 0
    filter_policy: str = "none"  # none | public_only | whitelist_keys


@dataclass
class DeployConfig:
    strategy: str = "docker"  # docker | vps | compose
    docker: Dict[str, Any] = field(default_factory=lambda: {
        "base_image": "python:3.11-slim",
        "port": 8000,
        "env_file_required": True,
    })
    vps: Dict[str, Any] = field(default_factory=lambda: {
        "ssh_user": "root",
        "ssh_host": "",
        "install_dir": "/opt/hermes-mirror",
    })


@dataclass
class Snapshot:
    """Complete mirror snapshot — the ur-canonical form."""
    manifest: Manifest = field(default_factory=Manifest)
    identity: Identity = field(default_factory=Identity)
    skills: List[SkillEntry] = field(default_factory=list)
    config: Dict[str, Any] = field(default_factory=dict)
    credentials: CredentialManifest = field(default_factory=CredentialManifest)
    memory_snapshot: MemoryPolicy = field(default_factory=MemoryPolicy)
    plugins: List[PluginEntry] = field(default_factory=list)
    dependencies: Dict[str, Any] = field(default_factory=lambda: {
        "python_packages": [],
        "system_packages": [],
        "hermes_version": ">=2.0.0",
    })
    deployment: DeployConfig = field(default_factory=DeployConfig)

    # -----------------------------------------------------------------------
    # Validation
    # -----------------------------------------------------------------------

    def validate(self) -> List[str]:
        """Return list of validation errors (empty = valid)."""
        errors: List[str] = []

        # Manifest
        if not self.manifest.mirror_id:
            errors.append("manifest.mirror_id is required")
        if not self.manifest.created_at:
            errors.append("manifest.created_at is required")

        # Skills — at minimum need names
        for i, s in enumerate(self.skills):
            if not s.name:
                errors.append(f"skills[{i}].name is required")

        # Config
        if not self.config.get("model", {}).get("default"):
            errors.append("config.model.default is required")

        # Dependencies
        if not self.dependencies.get("hermes_version"):
            errors.append("dependencies.hermes_version is required")

        # Deployment
        strat = self.deployment.strategy
        if strat not in ("docker", "vps", "compose"):
            errors.append(f"deployment.strategy must be docker, vps, or compose (got '{strat}')")

        return errors

    # -----------------------------------------------------------------------
    # Serialization
    # -----------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        return _deep_clean(asdict(self))

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Snapshot":
        kwargs: Dict[str, Any] = {}

        if "manifest" in data:
            kwargs["manifest"] = Manifest(**data["manifest"])
        if "identity" in data:
            kwargs["identity"] = Identity(**data["identity"])
        if "skills" in data:
            kwargs["skills"] = [SkillEntry(**s) for s in data["skills"]]
        if "config" in data:
            kwargs["config"] = data["config"]
        if "credentials" in data:
            kwargs["credentials"] = CredentialManifest(**data["credentials"])
        if "memory_snapshot" in data:
            kwargs["memory_snapshot"] = MemoryPolicy(**data["memory_snapshot"])
        if "plugins" in data:
            kwargs["plugins"] = [PluginEntry(**p) for p in data["plugins"]]
        if "dependencies" in data:
            kwargs["dependencies"] = data["dependencies"]
        if "deployment" in data:
            kwargs["deployment"] = DeployConfig(**data["deployment"])

        return cls(**kwargs)

    @classmethod
    def from_json(cls, text: str) -> "Snapshot":
        return cls.from_dict(json.loads(text))

    @classmethod
    def from_json_file(cls, path: str) -> "Snapshot":
        with open(path, "r") as f:
            return cls.from_dict(json.load(f))


def _deep_clean(obj: Any) -> Any:
    """Remove None values and empty strings from nested dicts/lists for clean JSON."""
    if isinstance(obj, dict):
        return {k: _deep_clean(v) for k, v in obj.items()
                if v is not None and v != "" and v != [] and v != {}}
    elif isinstance(obj, list):
        cleaned = [_deep_clean(i) for i in obj if i is not None]
        return cleaned if cleaned else []
    return obj
