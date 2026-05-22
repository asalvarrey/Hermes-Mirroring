"""Sub-Agent Mirroring — Sanitizer (Privacy Shield integration)

Scrubs PII, API keys, personal data, and sensitive content from
a snapshot before packaging it for deployment to a third party.

Uses the same pattern-based detection as the Privacy Guardrails plugin
but operates at the snapshot level rather than per-message.

Detection layers:
  1. Regex patterns — API keys, tokens, JWTs, SSH keys, crypto wallets
  2. Entropy detection — high-entropy strings that look like secrets
  3. Email/phone — personal contact info
  4. Identity fields — user IDs, platform handles, names
"""

from __future__ import annotations

import os
import re
import logging
from typing import Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Regex patterns — one source of truth
# ---------------------------------------------------------------------------

PATTERNS: Dict[str, re.Pattern] = {
    # --- API Keys & Tokens ---
    "aws_access_key": re.compile(
        r"(?<![A-Za-z0-9/+])(AKIA[0-9A-Z]{16})(?![A-Za-z0-9/+])"
    ),
    "aws_secret_key": re.compile(
        r"(?<![A-Za-z0-9/+])(aws(.{0,20})?(s[-\s]?e[-\s]?c[-\s]?r[-\s]?e[-\s]?t|"
        r"secret(.{0,20})?key)[:\s]*['\"]?([A-Za-z0-9/+]{40}))",
        re.IGNORECASE,
    ),
    "github_token": re.compile(
        r"(?<![A-Za-z0-9])(ghp_|gho_|ghu_|ghs_|ghr_)[A-Za-z0-9_]{36,}(?![A-Za-z0-9_])"
    ),
    "github_fine_grained": re.compile(
        r"(?<![A-Za-z0-9])(github_pat_)[A-Za-z0-9_]{82,}(?![A-Za-z0-9_])"
    ),
    "supabase_key": re.compile(
        r"(?<![A-Za-z0-9])(sbp_|eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9)[A-Za-z0-9_\-\.]{20,}(?![A-Za-z0-9])"
    ),
    "openai_key": re.compile(
        r"(?<![A-Za-z0-9])(sk-[A-Za-z0-9]{20}T3BlbkFJ[A-Za-z0-9]{20})(?![A-Za-z0-9])"
    ),
    "openai_key_short": re.compile(
        r"(?<![A-Za-z0-9])sk-[A-Za-z0-9]{20,55}(?![A-Za-z0-9])"
    ),
    "anthropic_key": re.compile(
        r"(?<![A-Za-z0-9])sk-ant-api[0-9]{2}-[A-Za-z0-9]{40,60}(?![A-Za-z0-9])"
    ),
    "google_api_key": re.compile(
        r"(?<![A-Za-z0-9])AIzaSy[A-Za-z0-9_-]{33}(?![A-Za-z0-9])"
    ),
    "slack_token": re.compile(
        r"(?<![A-Za-z0-9])(xox[baprs]-[0-9]{10,14}-[0-9]{10,14}-[A-Za-z0-9]{20,30})(?![A-Za-z0-9])"
    ),
    "discord_token": re.compile(
        r"(?<![A-Za-z0-9])([MN][A-Za-z\d]{23}\.[Xx]\.[A-Za-z\d\-_]{6,})(?![A-Za-z0-9])"
    ),
    "jwt_token": re.compile(
        r"eyJ[A-Za-z0-9_\-]{10,}\.(eyJ[A-Za-z0-9_\-]{10,}|[A-Za-z0-9_\-]{10,})\.[A-Za-z0-9_\-]{10,}"
    ),
    "heroku_api": re.compile(
        r"(?<![A-Za-z0-9])(h[ru]k[ou]-\w{20,40})(?![A-Za-z0-9])"
    ),
    "mailgun_key": re.compile(
        r"key-[0-9a-fA-F]{32}"
    ),
    "twilio_key": re.compile(
        r"SK[0-9a-fA-F]{32}"
    ),
    "sendgrid_key": re.compile(
        r"SG\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}"
    ),
    "stripe_live": re.compile(
        r"(?<![A-Za-z0-9])(sk_live_[0-9a-zA-Z]{20,40})(?![A-Za-z0-9])"
    ),
    "stripe_test": re.compile(
        r"(?<![A-Za-z0-9])(sk_test_[0-9a-zA-Z]{20,40})(?![A-Za-z0-9])"
    ),
    "telegram_bot_token": re.compile(
        r"(?<![A-Za-z0-9])([0-9]{8,10}:[A-Za-z0-9_-]{35,})(?![A-Za-z0-9])"
    ),
    "private_key_header": re.compile(
        r"-----BEGIN\s?(RSA|DSA|EC|OPENSSH|PGP)?\s?PRIVATE KEY-----"
    ),
    "ssh_private_key_line": re.compile(
        r"[A-Za-z0-9+/]{50,}={0,2}\s*$", re.MULTILINE
    ),

    # --- Crypto wallets ---
    "eth_address": re.compile(
        r"(?<![A-Za-z0-9])(0x[a-fA-F0-9]{40})(?![A-Za-z0-9])"
    ),
    "bitcoin_address": re.compile(
        r"(?<![A-Za-z0-9])([13][a-km-zA-HJ-NP-Z1-9]{25,34})(?![A-Za-z0-9])"
    ),
    "btc_segwit": re.compile(
        r"(?<![A-Za-z0-9])(bc1[a-zA-HJ-NP-Z0-9]{25,39})(?![A-Za-z0-9])"
    ),

    # --- Contact info ---
    "email": re.compile(
        r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"
    ),
    "phone_us": re.compile(
        r"\b(\+1[-\s.]?)?\(?[2-9][0-9]{2}\)?[-\s.]?[2-9][0-9]{2}[-\s.]?[0-9]{4}\b"
    ),
    "phone_international": re.compile(
        r"\+\d{1,3}[-\s.]?\d{1,14}([-\s.]?\d{1,13})?"
    ),

    # --- Infrastructure ---
    "ip_address_internal": re.compile(
        r"\b(10\.\d{1,3}\.\d{1,3}\.\d{1,3}|172\.(1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}|"
        r"192\.168\.\d{1,3}\.\d{1,3}|127\.\d{1,3}\.\d{1,3}\.\d{1,3})\b"
    ),
    "supabase_url": re.compile(
        r"https://[a-zA-Z0-9-]+\.supabase\.co"
    ),
    "ngrok_url": re.compile(
        r"https?://[a-zA-Z0-9-]+\.ngrok[a-z0-9-]*\.(io|app|dev)"
    ),
    "local_db_url": re.compile(
        r"postgres(ql)?://[^:]+:[^@]+@[^/]+/\w+"
    ),
    "redis_url": re.compile(
        r"redis://[^:]+:[^@]+@[^/]+"
    ),

    # --- Identity ---
    "discord_user_id": re.compile(
        r"\b[0-9]{17,19}\b"
    ),
}


class Sanitizer:
    """Scrub sensitive data from snapshot content.

    Phases:
      1. Detect & redact all known patterns with placeholders
      2. Optionally compute entropy on unknown strings
      3. Block identity fields by key name
      4. Log what was redacted (metadata only, never values)
    """

    # Patterns that, when detected, require the whole line to be removed
    # (credential values spanning multiple tokens)
    FULL_LINE_PATTERNS = {
        "private_key_header", "ssh_private_key_line",
    }

    BLOCKED_IDENTITY_KEYS = {
        "password", "secret", "api_key", "api_secret", "token",
        "auth_token", "access_token", "refresh_token",
        "private_key", "ssh_key", "service_key",
        "discord_id", "telegram_id", "user_id", "session_id",
        "phone", "phone_number", "email", "address",
        "ssn", "credit_card", "passport", "dni",
    }

    def __init__(self, profile: str = "standard"):
        """profile: 'standard' | 'minimal' | 'paranoid' | 'minimal_plus_email'"""
        self.profile = profile
        self._redaction_log: List[Tuple[str, str, int]] = []  # (pattern, placeholder, count)
        self._counter: int = 0

    def sanitize_text(self, text: str) -> str:
        """Scan and redact sensitive data from a text block."""
        result = text

        # Phase 1: Inline replacements FIRST (before full-line patterns)
        # This prevents greedy patterns like ssh_private_key_line from
        # eating tokens that have specific patterns (OpenAI keys, GitHub tokens, etc.)
        for name, pattern in PATTERNS.items():
            if name in self.FULL_LINE_PATTERNS:
                continue
            if not self._should_check(name):
                continue

            def make_replacer(n=name):
                def replacer(m: re.Match) -> str:
                    self._counter += 1
                    placeholder = f"<{n.upper()}_{self._counter}>"
                    self._redaction_log.append((n, placeholder, 1))
                    return placeholder
                return replacer

            result = pattern.sub(make_replacer(), result)

        # Phase 2: Full-line removals (private key blocks, SSH key lines, etc.)
        for name, pattern in PATTERNS.items():
            if name in self.FULL_LINE_PATTERNS and self._should_check(name):
                result = self._redact_lines(result, pattern, name)

        # Phase 3: Entropy-based (paranoid only)
        if self.profile == "paranoid":
            result = self._entropy_scan(result)

        return result

    def sanitize_dict(self, data: dict, parent_key: str = "") -> dict:
        """Recursively sanitize a dict. Blocks known identity keys entirely."""
        result = {}
        blocked_keys_found = set()

        for key, value in data.items():
            # Check if key should be blocked — if so, replace and skip value processing
            blocked = False
            for blocked_prefix in self.BLOCKED_IDENTITY_KEYS:
                if blocked_prefix.lower() in key.lower():
                    result[key] = f"<{key.upper()}_REDACTED>"
                    self._redaction_log.append(
                        (f"blocked_key:{key}", f"<{key.upper()}_REDACTED>", 1)
                    )
                    blocked = True
                    break

            if blocked:
                continue  # Skip value processing — key is already redacted

            if isinstance(value, dict):
                result[key] = self.sanitize_dict(value, parent_key=f"{parent_key}.{key}")
            elif isinstance(value, list):
                result[key] = [self.sanitize_dict(v, parent_key) if isinstance(v, dict)
                               else self.sanitize_text(str(v)) if isinstance(v, str)
                               else v
                               for v in value]
            elif isinstance(value, str):
                result[key] = self.sanitize_text(value)
            else:
                result[key] = value

        return result

    def sanitize_config(self, config: dict) -> dict:
        """Sanitize the config dict, protecting specific keys from being stripped."""
        protected_keys = {"model", "toolsets", "agent", "memory"}

        # Strip .env references from config
        config = self.sanitize_dict(config)

        # Remove known env_var sections that contain actual values
        if "env" in config:
            config["env"] = "<ENV_BLOCK_REDACTED>"

        return config

    def redaction_summary(self) -> str:
        """Return human-readable summary of what was redacted."""
        if not self._redaction_log:
            return "✅ No sensitive data detected."

        by_pattern: Dict[str, int] = {}
        for pattern, _, count in self._redaction_log:
            by_pattern[pattern] = by_pattern.get(pattern, 0) + count

        lines = [f"🔒 {sum(by_pattern.values())} items redacted:"]
        for name, count in sorted(by_pattern.items(), key=lambda x: -x[1]):
            lines.append(f"   - {name}: {count}")
        return "\n".join(lines)

    def reset_log(self) -> None:
        self._redaction_log = []
        self._counter = 0

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _should_check(self, pattern_name: str) -> bool:
        """Determine whether a pattern should be checked given the profile."""
        paranoid_only = {"phone_international", "ip_address_internal"}
        minimal_skip = {"phone_international", "phone_us", "ip_address_internal",
                        "local_db_url", "redis_url", "ngrok_url",
                        "eth_address", "bitcoin_address", "btc_segwit"}

        if self.profile == "minimal":
            if pattern_name in minimal_skip:
                return False
        elif self.profile == "minimal_plus_email":
            if pattern_name in minimal_skip and pattern_name != "email":
                return False
            return True
        elif self.profile == "paranoid":
            return True
        elif self.profile == "devops":
            # Only infra/cloud patterns
            devops_whitelist = {"aws_access_key", "aws_secret_key", "github_token",
                                "github_fine_grained", "supabase_key", "ssh_private_key_line",
                                "private_key_header", "ip_address_internal", "local_db_url",
                                "redis_url", "supabase_url", "ngrok_url",
                                "discord_token", "slack_token"}
            return pattern_name in devops_whitelist

        # standard = default
        if pattern_name in paranoid_only:
            return False

        return True

    def _redact_lines(self, text: str, pattern: re.Pattern, name: str) -> str:
        """Replace entire lines matching a pattern with a placeholder."""
        lines = text.split("\n")
        result = []
        for line in lines:
            if pattern.search(line):
                self._counter += 1
                placeholder = f"<{name.upper()}_LINE_{self._counter}>"
                self._redaction_log.append((name, placeholder, 1))
                result.append(placeholder)
            else:
                result.append(line)
        return "\n".join(result)

    def _entropy_scan(self, text: str) -> str:
        """High-entropy detection for unknown secrets (paranoid mode only)."""
        import math

        def shannon_entropy(s: str) -> float:
            if not s:
                return 0.0
            prob = [s.count(c) / len(s) for c in set(s)]
            return -sum(p * math.log2(p) for p in prob)

        words = text.split()
        result_words = []
        for word in words:
            # Only check reasonably long, mixed-case alphanumeric strings
            stripped = word.strip(".,;:!?\"'()[]{}")
            if (len(stripped) >= 20
                    and any(c.isupper() for c in stripped)
                    and any(c.islower() for c in stripped)
                    and any(c.isdigit() for c in stripped)
                    and shannon_entropy(stripped) > 4.5):
                # Check if it's NOT already a placeholder
                if not stripped.startswith("<") and not stripped.endswith(">"):
                    self._counter += 1
                    placeholder = f"<HIGH_ENTROPY_{self._counter}>"
                    self._redaction_log.append(("entropy_detected", placeholder, 1))
                    result_words.append(placeholder)
                    continue
            result_words.append(word)

        return " ".join(result_words)
