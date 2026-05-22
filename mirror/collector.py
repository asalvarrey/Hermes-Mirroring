"""Sub-Agent Mirroring — Collector Engine

Gathers all Hermes data for a snapshot: skills, config, plugins,
memory references, vault metadata. Each collection phase feeds
through the Sanitizer before being added to the snapshot.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from .sanitizer import Sanitizer
from .schema import (
    Snapshot, Manifest, Identity, SkillEntry, PluginEntry,
    MemoryPolicy, CredentialManifest, DeployConfig,
)
from .memory_extractor import MemoryExtractor, MemoryExport

logger = logging.getLogger(__name__)

HERMES_HOME = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))
CACHE_DIR = HERMES_HOME / "cache" / "mirror"
SKILLS_DIR = HERMES_HOME / "skills"
PLUGINS_DIR = HERMES_HOME / "plugins"
CONFIG_PATH = HERMES_HOME / "config.yaml"
ENV_PATH = HERMES_HOME / ".env"
VAULT_DIR = Path.home() / ".password-store" / "hermes" / "vault"


class Collector:
    """Collects all Hermes data for a mirror snapshot.

    Phases:
      0. Build manifest & identity metadata
      1. Collect skills (names, hashes, content)
      2. Collect config (model, toolsets, agent settings)
      3. Collect plugins (names, versions, enabled states)
      4. Collect credential env-var names (never values)
      5. Optionally collect memory (filtered)
      6. Build deployment spec

    All text content passes through the Sanitizer.
    """

    def __init__(
        self,
        mirror_id: str = "",
        description: str = "",
        tags: Optional[List[str]] = None,
        profile: str = "standard",
        include_memory: bool = False,
        include_plugin_source: bool = False,
        memory_filter_policy: str = "none",
        memory_entry_limit: int = 500,
        output_dir: Optional[str] = None,
    ):
        self.mirror_id = mirror_id or f"hermes-mirror-{uuid.uuid4().hex[:8]}"
        self.description = description
        self.tags = tags or []
        self.profile = profile
        self.include_memory = include_memory
        self.include_plugin_source = include_plugin_source
        self.memory_filter_policy = memory_filter_policy
        self.memory_entry_limit = memory_entry_limit
        self.output_dir = Path(output_dir or CACHE_DIR)
        self.sanitizer = Sanitizer(profile=profile)
        self._memory_export: Optional[MemoryExport] = None

        self._skills_dir = SKILLS_DIR
        self._plugins_dir = PLUGINS_DIR
        self._config_path = CONFIG_PATH

    @property
    def memory_export(self) -> Optional[MemoryExport]:
        """The MemoryExport (if include_memory was True)."""
        return self._memory_export

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def collect(self) -> Snapshot:
        """Run all collection phases and return a Snapshot."""
        logger.info("Mirror collect: starting snapshot %s", self.mirror_id)

        # Phase: Memory extraction (may connect to Supabase or SQLite)
        memory_policy = self._collect_memory()

        snapshot = Snapshot(
            manifest=self._build_manifest(),
            identity=self._build_identity(),
            skills=self._collect_skills(),
            plugins=self._collect_plugins(),
            config=self._collect_config(),
            credentials=self._build_credential_manifest(),
            memory_snapshot=memory_policy,
            deployment=self._build_deploy_config(),
        )

        # Validate
        errors = snapshot.validate()
        if errors:
            raise ValueError(f"Snapshot validation errors:\n" + "\n".join(f"  - {e}" for e in errors))

        entries = self._memory_export.entry_count() if self._memory_export else 0
        logger.info("Mirror collect: snapshot %s ready (%d skills, %d plugins, %d memory entries)",
                     self.mirror_id, len(snapshot.skills), len(snapshot.plugins), entries)

        return snapshot

    def collect_to_file(self, snapshot: Optional[Snapshot] = None) -> Path:
        """Write snapshot + memory bundle to output directory. Returns path to snapshot.json."""
        snapshot = snapshot or self.collect()
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # 1. Snapshot manifest
        out_path = self.output_dir / "snapshot.json"
        out_path.write_text(snapshot.to_json(), encoding="utf-8")

        # 2. Memory bundle (SQL + JSON) if extracted
        if self._memory_export and self._memory_export.entry_count() > 0:
            sql_path = self.output_dir / "memory_restore.sql"
            sql_path.write_text(self._memory_export.to_sql(), encoding="utf-8")
            logger.info("Mirror collect: memory SQL written to %s (%d entries, %.1f KB)",
                         sql_path, self._memory_export.entry_count(),
                         sql_path.stat().st_size / 1024)

            json_path = self.output_dir / "memory_export.json"
            json_path.write_text(self._memory_export.to_json(), encoding="utf-8")
            logger.info("Mirror collect: memory JSON written to %s", json_path)

        # 3. Redaction log
        summary = self.sanitizer.redaction_summary()
        if "✅" not in summary:
            log_path = self.output_dir / "redaction_log.txt"
            log_path.write_text(summary, encoding="utf-8")
            logger.info("Mirror collect: redaction log written to %s", log_path)

        return out_path

    # ------------------------------------------------------------------
    # Phase 0 — Manifest
    # ------------------------------------------------------------------

    def _build_manifest(self) -> Manifest:
        return Manifest(
            version="1.0.0",
            created_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            original_id=self._get_original_id(),
            mirror_id=self.mirror_id,
            description=self.description,
            tags=self.tags,
        )

    def _get_original_id(self) -> str:
        """Derive an ID for the source Hermes instance."""
        config = self._load_config_raw()
        model_default = config.get("model", {}).get("default", "unknown")
        provider = config.get("model", {}).get("provider", "unknown")
        return f"hermes-{provider}-{model_default.split('/')[-1]}"

    # ------------------------------------------------------------------
    # Phase 0b — Identity
    # ------------------------------------------------------------------

    def _build_identity(self) -> Identity:
        return Identity(
            name=self.mirror_id,
            personality=f"mirror of {self._get_original_id()}",
            system_prompt_extra=self._get_personality_text(),
        )

    def _get_personality_text(self) -> str:
        config = self._load_config_raw()
        personality = config.get("agent", {}).get("personalities", {}).get("helpful", "")
        return personality

    # ------------------------------------------------------------------
    # Phase 1 — Skills
    # ------------------------------------------------------------------

    def _collect_skills(self) -> List[SkillEntry]:
        if not self._skills_dir.exists():
            logger.info("Mirror collect: no skills dir at %s", self._skills_dir)
            return []

        skills: List[SkillEntry] = []
        for item in sorted(self._skills_dir.iterdir()):
            if not item.is_dir():
                continue
            skill_md = item / "SKILL.md"
            if not skill_md.exists():
                continue

            raw_content = skill_md.read_text(encoding="utf-8")
            sanitized = self.sanitizer.sanitize_text(raw_content)
            content_hash = hashlib.sha256(sanitized.encode()).hexdigest()

            # Extract version from YAML frontmatter
            version = self._extract_yaml_field(raw_content, "version") or "0.0.0"

            skills.append(SkillEntry(
                name=item.name,
                version=version,
                content_hash=f"sha256:{content_hash}",
                content=sanitized,
            ))
            logger.debug("Mirror collect: skill '%s' (v%s)", item.name, version)

        return skills

    @staticmethod
    def _extract_yaml_field(text: str, field: str) -> Optional[str]:
        """Simple frontmatter parser — extract a YAML field value."""
        if not text.startswith("---"):
            return None
        end = text.find("---", 3)
        if end == -1:
            return None
        frontmatter = text[3:end]
        for line in frontmatter.split("\n"):
            line = line.strip()
            if line.startswith(f"{field}:") or line.startswith(f"{field}:"):
                value = line.split(":", 1)[1].strip().strip('"').strip("'")
                return value if value else None
        return None

    # ------------------------------------------------------------------
    # Phase 2 — Config
    # ------------------------------------------------------------------

    def _collect_config(self) -> Dict[str, Any]:
        config = self._load_config_raw()
        if not config:
            return self._default_config()

        # Strip sensitive fields
        safe_config = {
            "model": config.get("model", {}),
            "toolsets": config.get("toolsets", []),
            "agent": self._sanitize_agent_config(config.get("agent", {})),
            "memory": config.get("memory", {}),
        }
        return self.sanitizer.sanitize_config(safe_config)

    @staticmethod
    def _sanitize_agent_config(agent: Dict[str, Any]) -> Dict[str, Any]:
        """Keep only safe fields from agent config."""
        safe_keys = {
            "max_turns", "reasoning_effort", "image_input_mode",
            "personalities", "verbose",
        }
        return {k: v for k, v in agent.items() if k in safe_keys}

    def _load_config_raw(self) -> Dict[str, Any]:
        try:
            import yaml
            if self._config_path.exists():
                text = self._config_path.read_text(encoding="utf-8")
                return yaml.safe_load(text) or {}
        except ImportError:
            pass
        return {}

    @staticmethod
    def _default_config() -> Dict[str, Any]:
        return {
            "model": {"default": "deepseek/deepseek-v4-flash", "provider": "nous"},
            "toolsets": ["hermes-cli"],
            "agent": {"max_turns": 90},
        }

    # ------------------------------------------------------------------
    # Phase 3 — Plugins
    # ------------------------------------------------------------------

    def _collect_plugins(self) -> List[PluginEntry]:
        if not self._plugins_dir.exists():
            logger.info("Mirror collect: no plugins dir at %s", self._plugins_dir)
            return []

        plugins: List[PluginEntry] = []
        for item in sorted(self._plugins_dir.iterdir()):
            if not item.is_dir():
                continue
            plugin_yaml = item / "plugin.yaml"
            if not plugin_yaml.exists():
                continue

            try:
                import yaml
                meta = yaml.safe_load(plugin_yaml.read_text(encoding="utf-8"))
            except Exception:
                meta = {}

            name = meta.get("name", item.name)
            version = meta.get("version", "0.0.0")

            # Hash the plugin code
            content_hash = self._hash_directory(item)
            config_data = self._extract_plugin_config(meta)

            plugins.append(PluginEntry(
                name=name,
                version=version,
                enabled=True,
                content_hash=f"sha256:{content_hash}",
                config=config_data,
            ))
            logger.debug("Mirror collect: plugin '%s' (v%s)", name, version)

        return plugins

    @staticmethod
    def _hash_directory(dir_path: Path) -> str:
        """Compute a sha256 over all files in a directory."""
        hasher = hashlib.sha256()
        for f in sorted(dir_path.rglob("*")):
            if f.is_file() and f.suffix not in (".pyc", ".pyo") and "__pycache__" not in f.parts:
                hasher.update(f.name.encode())
                hasher.update(f.read_bytes())
        return hasher.hexdigest()

    @staticmethod
    def _extract_plugin_config(meta: dict) -> dict:
        """Get safe config from plugin metadata — env_var names, not values."""
        return {
            "env_vars": meta.get("env_vars", []),
            "install_deps": meta.get("install_deps", []),
            "tags": meta.get("tags", []),
        }

    # ------------------------------------------------------------------
    # Phase 4 — Credentials manifest
    # ------------------------------------------------------------------

    def _build_credential_manifest(self) -> CredentialManifest:
        """Identify env vars needed but never include their values."""
        env_vars: Set[str] = set()

        # From config
        config = self._load_config_raw()
        providers = config.get("providers", {})
        for prov_name, prov_config in providers.items():
            if isinstance(prov_config, dict):
                for key in prov_config:
                    if "key" in key.lower() or "token" in key.lower() or "secret" in key.lower():
                        env_var = prov_config[key]
                        if isinstance(env_var, str) and env_var.startswith("${") and env_var.endswith("}"):
                            env_vars.add(env_var[2:-1])

        # From plugins
        for plugin in self._collect_plugins():
            env_vars.update(plugin.config.get("env_vars", []))

        # Common env vars from .env file (header only)
        if ENV_PATH.exists():
            try:
                for line in ENV_PATH.read_text().splitlines():
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        var_name = line.split("=", 1)[0].strip()
                        if var_name and var_name.isupper():
                            env_vars.add(var_name)
            except Exception:
                pass

        return CredentialManifest(
            env_vars=sorted(env_vars),
            values_placeholder=True,
            notes="Supply real values via --env-file at deploy time.",
        )

    # ------------------------------------------------------------------
    # Phase 5 — Memory policy
    # ------------------------------------------------------------------

    def _collect_memory(self) -> MemoryPolicy:
        """Extract memory from Supabase or SQLite, sanitize, and store in self._memory_export.

        Returns a MemoryPolicy describing what was collected.
        Gracefully degrades: if no memory source is available, returns empty policy.
        """
        if not self.include_memory:
            self._memory_export = MemoryExport(
                source_id=f"hermes-{self.mirror_id}",
                created_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                sanitized=True,
            )
            return MemoryPolicy(included=False)

        logger.info("Mirror collect: extracting memory (limit=%d, profile=%s)",
                     self.memory_entry_limit, self.profile)

        extractor = MemoryExtractor(
            profile=self.profile,
            memory_limit=self.memory_entry_limit,
            include_sessions=False,
            sanitizer=self.sanitizer,
        )

        try:
            self._memory_export = extractor.extract()
        except Exception as e:
            logger.warning("Mirror collect: memory extraction failed: %s", e)
            self._memory_export = MemoryExport(
                source_id=f"hermes-{self.mirror_id}",
                created_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                sanitized=True,
            )

        count = self._memory_export.entry_count()
        size = self._memory_export.size_estimate()
        logger.info("Mirror collect: %d memory entries (~%.1f KB) extracted",
                     count, size / 1024)

        return MemoryPolicy(
            included=count > 0,
            size_bytes=size,
            entries=count,
            filter_policy=self.memory_filter_policy,
        )

    # ------------------------------------------------------------------
    # Phase 6 — Deploy config
    # ------------------------------------------------------------------

    @staticmethod
    def _build_deploy_config() -> DeployConfig:
        return DeployConfig(
            strategy="docker",
            docker={
                "base_image": "python:3.11-slim",
                "port": 8000,
                "env_file_required": True,
                "hermes_install": "pip install hermes-agent",
            },
            vps={
                "ssh_user": "root",
                "ssh_host": "",
                "install_dir": "/opt/hermes-mirror",
            },
        )
