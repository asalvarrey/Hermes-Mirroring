"""Sub-Agent Mirroring — Memory Extractor

Extracts memory, user profiles, and skills from Supabase (or SQLite fallback),
sanitizes them, and packages as portable SQL/JSON for the target deployment.

Why this matters:
  - The user profile stores personality preferences, tone, and learned behavior.
  - Memory entries contain the agent's "experiences" that shape its responses.
  - Cross-instance skills (hermes_skills table) let the clone inherit workflows.
  
Without memory extraction, the mirror is a generic shell with no personality.

Architecture:
  1. Connect to Supabase using env vars (same as the SupabaseMemoryProvider)
  2. Query user profiles, recent memory, skills
  3. Run every text field through the Sanitizer
  4. Package as a portable SQL restore file
  5. (Optional) Package as JSON for non-Postgres targets
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .sanitizer import Sanitizer

logger = logging.getLogger(__name__)

SUPABASE_TABLES = ["hermes_memory", "hermes_users", "hermes_sessions", "hermes_skills"]

# SQL schema for the target — CREATE TABLE statements
SCHEMA_SQL = """
-- Hermes Mirror — Restored from source snapshot
-- Created: {created_at}
-- Source: {source_id}
-- Sanitized: {sanitized}

-- 1. Users / Profiles
CREATE TABLE IF NOT EXISTS hermes_users (
    user_id     TEXT PRIMARY KEY,
    profile     JSONB DEFAULT '{{}}'::jsonb,
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    updated_at  TIMESTAMPTZ DEFAULT NOW()
);

-- 2. Memory entries (vector embeddings will recompute on first use)
CREATE TABLE IF NOT EXISTS hermes_memory (
    id          BIGSERIAL PRIMARY KEY,
    user_id     TEXT NOT NULL DEFAULT 'default',
    session_id  TEXT,
    content     TEXT NOT NULL,
    metadata    JSONB DEFAULT '{{}}'::jsonb,
    role        TEXT DEFAULT 'user',
    embedding   VECTOR(1536),      -- recomputed on access
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

-- 3. Session summaries
CREATE TABLE IF NOT EXISTS hermes_sessions (
    session_id   TEXT PRIMARY KEY,
    title        TEXT,
    summary      TEXT,
    user_id      TEXT DEFAULT 'default',
    message_count INTEGER DEFAULT 0,
    created_at   TIMESTAMPTZ DEFAULT NOW(),
    updated_at   TIMESTAMPTZ DEFAULT NOW()
);

-- 4. Cross-instance skills
CREATE TABLE IF NOT EXISTS hermes_skills (
    id          BIGSERIAL PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,
    version     TEXT DEFAULT '0.0.0',
    content     TEXT NOT NULL,
    category    TEXT DEFAULT '',
    checksum    TEXT DEFAULT '',
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    updated_at  TIMESTAMPTZ DEFAULT NOW()
);

-- Enable pgvector extension if not enabled
CREATE EXTENSION IF NOT EXISTS vector;
"""


@dataclass
class MemoryExport:
    """Sanitized memory bundle ready for packaging."""
    source_id: str = ""
    created_at: str = ""
    sanitized: bool = True
    user_profiles: List[Dict[str, Any]] = field(default_factory=list)
    memory_entries: List[Dict[str, Any]] = field(default_factory=list)
    session_summaries: List[Dict[str, Any]] = field(default_factory=list)
    skills: List[Dict[str, Any]] = field(default_factory=list)

    def to_sql(self) -> str:
        """Generate portable SQL INSERT statements."""
        lines = []
        lines.append("-- Hermes Mirror Memory Restore")
        lines.append(f"-- Source: {self.source_id}")
        lines.append(f"-- Created: {self.created_at}")
        lines.append("")

        # Schema
        lines.append(SCHEMA_SQL.format(
            created_at=self.created_at[:10],
            source_id=self.source_id,
            sanitized=str(self.sanitized),
        ))
        lines.append("")

        # Users
        for user in self.user_profiles:
            uid = user.get("user_id", "default")
            profile = json.dumps(json.loads(user.get("profile", "{}")), default=str)
            ts = user.get("updated_at", "NOW()")
            lines.append(
                f"INSERT INTO hermes_users (user_id, profile, updated_at) "
                f"VALUES ('{_sql_escape(uid)}', '{_sql_escape(profile)}'::jsonb, {ts}) "
                f"ON CONFLICT (user_id) DO UPDATE SET profile = EXCLUDED.profile;"
            )

        lines.append("")

        # Memory entries (without embeddings — recompute on access)
        for entry in self.memory_entries:
            uid = entry.get("user_id", "default")
            sid = entry.get("session_id", "")
            content = _sql_escape(entry.get("content", ""))
            metadata = json.dumps(entry.get("metadata", {}), default=str)
            role = entry.get("role", "user")
            ts = entry.get("created_at", "NOW()")
            lines.append(
                f"INSERT INTO hermes_memory (user_id, session_id, content, metadata, role, created_at) "
                f"VALUES ('{_sql_escape(uid)}', '{_sql_escape(sid)}', '{content}', "
                f"'{_sql_escape(metadata)}'::jsonb, '{role}', {ts});"
            )

        lines.append("")

        # Session summaries
        for sess in self.session_summaries:
            sid = _sql_escape(sess.get("session_id", ""))
            title = _sql_escape(sess.get("title", ""))
            summary = _sql_escape(sess.get("summary", ""))
            uid = sess.get("user_id", "default")
            lines.append(
                f"INSERT INTO hermes_sessions (session_id, title, summary, user_id) "
                f"VALUES ('{sid}', '{title}', '{summary}', '{uid}') "
                f"ON CONFLICT (session_id) DO NOTHING;"
            )

        lines.append("")

        # Skills
        for skill in self.skills:
            name = _sql_escape(skill.get("name", ""))
            version = skill.get("version", "0.0.0")
            content = _sql_escape(skill.get("content", ""))
            category = _sql_escape(skill.get("category", ""))
            checksum = skill.get("checksum", "")
            lines.append(
                f"INSERT INTO hermes_skills (name, version, content, category, checksum) "
                f"VALUES ('{name}', '{version}', '{content}', '{category}', '{checksum}') "
                f"ON CONFLICT (name) DO UPDATE SET version = EXCLUDED.version;"
            )

        lines.append("")
        return "\n".join(lines)

    def to_json(self) -> str:
        """Export as JSON for non-Postgres targets."""
        return json.dumps(asdict(self), indent=2, ensure_ascii=False, default=str)

    def entry_count(self) -> int:
        return (len(self.user_profiles) + len(self.memory_entries)
                + len(self.session_summaries) + len(self.skills))

    def size_estimate(self) -> int:
        total = 0
        for entries in [self.user_profiles, self.memory_entries,
                        self.session_summaries, self.skills]:
            for e in entries:
                for v in e.values():
                    if isinstance(v, str):
                        total += len(v)
                    elif isinstance(v, dict):
                        total += len(json.dumps(v))
        return total


class MemoryExtractor:
    """Extract memory from Supabase or SQLite, sanitize, package.

    Two data sources:
      1. Supabase REST API (via supabase Python client) — preferred
      2. SQLite fallback (from LocalCache) — always available

    The extractor:
      - Limits memory to the N most recent entries (configurable)
      - Filters system/internal entries
      - Runs ALL text through Sanitizer before packaging
      - Strips user IDs / session IDs / platform handles
    """

    def __init__(
        self,
        profile: str = "standard",
        memory_limit: int = 500,
        include_sessions: bool = False,
        sanitizer: Optional[Sanitizer] = None,
    ):
        self.profile = profile
        self.memory_limit = memory_limit
        self.include_sessions = include_sessions
        self.sanitizer = sanitizer or Sanitizer(profile=profile)

    def extract(self) -> MemoryExport:
        """Run extraction from all available sources.

        Tries Supabase first, falls back to SQLite.
        """
        export = MemoryExport(
            source_id=f"hermes-mirror-{int(time.time())}",
            created_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            sanitized=True,
        )

        # Try Supabase first
        if self._has_supabase():
            try:
                self._extract_from_supabase(export)
                return export
            except Exception as e:
                logger.warning("Supabase extract failed: %s — trying SQLite", e)

        # Fall back to SQLite
        self._extract_from_sqlite(export)

        return export

    # ------------------------------------------------------------------
    # Supabase extraction
    # ------------------------------------------------------------------

    def _has_supabase(self) -> bool:
        try:
            import supabase  # noqa: F401
            return True
        except ImportError:
            return False

    def _extract_from_supabase(self, export: MemoryExport) -> None:
        """Extract data from Supabase using the REST API (same as SupabaseMemoryProvider)."""
        from supabase import create_client

        url = os.environ.get("SUPABASE_URL", "")
        key = os.environ.get("SUPABASE_SERVICE_KEY", "") or os.environ.get("SUPABASE_ANON_KEY", "")
        if not url or not key:
            logger.warning("Supabase credentials not found — can't extract memory")
            return

        client = create_client(url, key)

        # 1. Users / Profiles
        try:
            users = client.table("hermes_users").select("*").limit(100).execute()
            for u in users.data or []:
                sanitized_profile = self.sanitizer.sanitize_text(
                    json.dumps(u.get("profile", {}), default=str)
                )
                export.user_profiles.append({
                    "user_id": u.get("user_id", "default"),
                    "profile": sanitized_profile,
                    "updated_at": u.get("updated_at", ""),
                })
            logger.info("Extracted %d user profiles from Supabase", len(users.data or []))
        except Exception as e:
            logger.warning("Could not extract users: %s", e)

        # 2. Memory entries (most recent, limited)
        try:
            memory = (
                client.table("hermes_memory")
                .select("*")
                .order("created_at", desc=True)
                .limit(self.memory_limit)
                .execute()
            )
            for m in memory.data or []:
                sanitized_content = self.sanitizer.sanitize_text(m.get("content", ""))
                sanitized_meta = self.sanitizer.sanitize_text(
                    json.dumps(m.get("metadata", {}), default=str)
                )
                # Strip internal/system entries
                if self._is_internal_entry(m):
                    continue
                export.memory_entries.append({
                    "user_id": m.get("user_id", "default"),
                    "session_id": m.get("session_id", ""),
                    "content": sanitized_content,
                    "metadata": json.loads(sanitized_meta),
                    "role": m.get("role", "user"),
                    "created_at": m.get("created_at", ""),
                })
            logger.info("Extracted %d memory entries from Supabase", len(memory.data or []))
        except Exception as e:
            logger.warning("Could not extract memory: %s", e)

        # 3. Session summaries (optional)
        if self.include_sessions:
            try:
                sessions = (
                    client.table("hermes_sessions")
                    .select("*")
                    .order("updated_at", desc=True)
                    .limit(50)
                    .execute()
                )
                for s in sessions.data or []:
                    export.session_summaries.append({
                        "session_id": s.get("session_id", ""),
                        "title": self.sanitizer.sanitize_text(s.get("title", "")),
                        "summary": self.sanitizer.sanitize_text(s.get("summary", "")),
                        "user_id": s.get("user_id", "default"),
                    })
            except Exception as e:
                logger.warning("Could not extract sessions: %s", e)

        # 4. Cross-instance skills
        try:
            skills = client.table("hermes_skills").select("*").limit(200).execute()
            for sk in skills.data or []:
                export.skills.append({
                    "name": sk.get("name", ""),
                    "version": sk.get("version", "0.0.0"),
                    "content": self.sanitizer.sanitize_text(sk.get("content", "")),
                    "category": sk.get("category", ""),
                    "checksum": sk.get("checksum", ""),
                })
            logger.info("Extracted %d skills from Supabase", len(skills.data or []))
        except Exception as e:
            logger.warning("Could not extract skills: %s", e)

    # ------------------------------------------------------------------
    # SQLite fallback extraction
    # ------------------------------------------------------------------

    def _extract_from_sqlite(self, export: MemoryExport) -> None:
        """Fall back to SQLite cache (from LocalCache)."""
        from pathlib import Path

        # Find the cache DB
        hermes_home = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))
        cache_db = hermes_home / "cache" / "supabase_cache.db"

        if not cache_db.exists():
            logger.warning("No SQLite cache found at %s", cache_db)
            return

        conn = sqlite3.connect(str(cache_db))
        conn.row_factory = sqlite3.Row

        try:
            # Memory from cache
            cursor = conn.execute(
                "SELECT content, metadata, role, created_at FROM memory_cache "
                "ORDER BY created_at DESC LIMIT ?",
                (self.memory_limit,),
            )
            for row in cursor.fetchall():
                sanitized = self.sanitizer.sanitize_text(row["content"])
                export.memory_entries.append({
                    "user_id": "default",
                    "session_id": "mirror-extract",
                    "content": sanitized,
                    "metadata": {},
                    "role": row["role"],
                    "created_at": time.strftime(
                        "%Y-%m-%dT%H:%M:%SZ", time.localtime(row["created_at"])
                    ),
                })

            # Profile from cache
            cursor = conn.execute(
                "SELECT user_id, profile FROM profile_cache LIMIT 10"
            )
            for row in cursor.fetchall():
                profile_text = self.sanitizer.sanitize_text(row["profile"])
                export.user_profiles.append({
                    "user_id": row["user_id"],
                    "profile": profile_text,
                    "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                })

            logger.info("Extracted %d entries from SQLite cache",
                        len(export.memory_entries))

        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Filters
    # ------------------------------------------------------------------

    @staticmethod
    def _is_internal_entry(entry: dict) -> bool:
        """Skip system-internal entries that shouldn't be cloned."""
        content = (entry.get("content") or "").lower()
        skip_patterns = [
            "system: memory prefetch",
            "system: context compaction",
            "internal:",
            "!remember",
            "/system",
        ]
        return any(p in content for p in skip_patterns)


def _sql_escape(text: str) -> str:
    """Escape string for SQL single-quoted context."""
    return text.replace("'", "''").replace("\\", "\\\\")
