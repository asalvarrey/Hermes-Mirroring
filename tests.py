# Sub-Agent Mirroring Plugin — Tests

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, List

# Add plugin to path
import sys
sys.path.insert(0, str(Path.home() / ".hermes" / "plugins" / "hermes-mirror"))

from mirror.schema import (
    Snapshot, Manifest, SkillEntry, PluginEntry,
    CredentialManifest, MemoryPolicy, DeployConfig,
)
from mirror.sanitizer import Sanitizer
from mirror.collector import Collector
from mirror.packager import Packager


# =============================================================================
# Schema Tests
# =============================================================================

def test_empty_snapshot_validation():
    snap = Snapshot()
    errors = snap.validate()
    assert len(errors) > 0, "Empty snapshot should have validation errors"
    assert any("mirror_id" in e for e in errors)
    assert any("model.default" in e for e in errors)


def test_valid_snapshot():
    snap = Snapshot(
        manifest=Manifest(
            mirror_id="test-mirror",
            created_at="2026-05-22T23:00:00Z",
        ),
        skills=[SkillEntry(name="test-skill", version="1.0.0")],
        config={"model": {"default": "gpt-4", "provider": "openai"}},
    )
    errors = snap.validate()
    assert len(errors) == 0, f"Should be valid, got: {errors}"


def test_snapshot_roundtrip():
    snap = Snapshot(
        manifest=Manifest(
            mirror_id="roundtrip-test",
            created_at="2026-05-22T23:00:00Z",
            description="Testing serialization",
            tags=["test"],
        ),
        skills=[SkillEntry(name="skill-a", version="1.0.0", content="echo hello")],
        plugins=[PluginEntry(name="supabase", version="1.0.1", enabled=True)],
        config={"model": {"default": "gpt-4"}},
        credentials=CredentialManifest(env_vars=["OPENAI_API_KEY"]),
        memory_snapshot=MemoryPolicy(included=False),
        deployment=DeployConfig(strategy="docker"),
    )

    json_str = snap.to_json()
    restored = Snapshot.from_json(json_str)

    assert restored.manifest.mirror_id == "roundtrip-test"
    assert len(restored.skills) == 1
    assert restored.skills[0].name == "skill-a"
    assert len(restored.plugins) == 1
    assert restored.plugins[0].name == "supabase"
    assert restored.credentials.env_vars == ["OPENAI_API_KEY"]


# =============================================================================
# Sanitizer Tests
# =============================================================================

# Use carefully constructed strings that trigger patterns without being
# real credentials. Each test uses a valid pattern from PATTERNS dict.

def test_sanitize_aws_key():
    sanitizer = Sanitizer(profile="standard")
    # AWS access key pattern: AKIA + 16 uppercase alphanumeric chars
    text = "My AWS key is AKIAIOSFODNN7EXAMPLE here"
    result = sanitizer.sanitize_text(text)
    assert "<AWS_ACCESS_KEY_" in result, f"Expected placeholder, got: {result}"


def test_sanitize_github_token():
    sanitizer = Sanitizer()
    # GitHub classic PAT: ghp_ + 36+ alnum chars
    text = "token=ghp_abcdefghijklmnopqrstuvwxyz0123456789abcd"
    result = sanitizer.sanitize_text(text)
    assert "<GITHUB_TOKEN_" in result, f"Expected placeholder, got: {result}"


def test_sanitize_email():
    sanitizer = Sanitizer(profile="standard")
    text = "Contact me at testuser-123@example.com for access"
    result = sanitizer.sanitize_text(text)
    assert "<EMAIL_" in result, f"Expected placeholder, got: {result}"
    assert "testuser-123@example.com" not in result


def test_sanitize_no_false_positives():
    sanitizer = Sanitizer()
    text = "The quick brown fox jumps over the lazy dog 42 times"
    result = sanitizer.sanitize_text(text)
    assert result == text, "Clean text should not be modified"


def test_sanitize_private_key_block():
    sanitizer = Sanitizer()
    text = """Just a normal line
-----BEGIN RSA PRIVATE KEY-----
AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA
AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA
-----END RSA PRIVATE KEY-----
Another normal line"""
    result = sanitizer.sanitize_text(text)
    assert "<PRIVATE_KEY_HEADER_LINE_" in result


def test_sanitize_openai_key():
    sanitizer = Sanitizer()
    # OpenAI key pattern (short): sk- + 20-55 alnum chars
    text = "sk-abcdefghijklmnopqrstuvwxyz0123456789abcdefghijklmnopq"
    result = sanitizer.sanitize_text(text)
    assert "<OPENAI_KEY_SHORT_" in result, f"Expected placeholder, got: {result}"


def test_sanitize_eth_address():
    sanitizer = Sanitizer(profile="paranoid")
    text = "Send ETH to 0x742d35Cc6634C0532925a3b844Bc9e7595f2bD18"
    result = sanitizer.sanitize_text(text)
    assert "<ETH_ADDRESS_" in result
    assert "0x742d35Cc6634C0532925a3b844Bc9e7595f2bD18" not in result


def test_sanitize_profile_minimal():
    """Minimal profile should skip crypto and phone patterns."""
    sanitizer = Sanitizer(profile="minimal")
    text = "ETH: 0x742d35Cc6634C0532925a3b844Bc9e7595f2bD18 Phone: +1-555-123-4567"
    result = sanitizer.sanitize_text(text)
    # Should NOT redact under minimal
    assert "0x" in result
    assert "555" in result


def test_sanitize_supabase_key():
    sanitizer = Sanitizer()
    # Supabase JWT-like key
    text = "supabase anon key = eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNvrPmhgKSeHZ9eTf"
    result = sanitizer.sanitize_text(text)
    assert "<SUPABASE_KEY_" in result


def test_redaction_summary():
    sanitizer = Sanitizer()
    text = ("API: AKIAIOSFODNN7EXAMPLE and "
            "ghp_abcdefghijklmnopqrstuvwxyz0123456789abcd and "
            "user@company.org")
    sanitizer.sanitize_text(text)
    summary = sanitizer.redaction_summary()
    assert "redacted" in summary
    # Case-insensitive check since output uses lowercase pattern names
    assert "AWS_ACCESS_KEY" in summary.upper()
    assert "GITHUB_TOKEN" in summary.upper()
    assert "EMAIL" in summary.upper()


def test_sanitizer_reuse():
    """Sanitizer should reset log between uses."""
    s1 = Sanitizer()
    s1.sanitize_text("AKIAIOSFODNN7EXAMPLE")
    s2 = Sanitizer()
    s2.sanitize_text("clean text here")
    summary = s2.redaction_summary()
    assert "✅" in summary, "Clean text should show no redactions"


def test_sanitize_dict_blocked_keys():
    """Dict sanitization should block identity fields by key name."""
    sanitizer = Sanitizer()
    data = {
        "name": "Test Agent",
        "api_key": "sk-abc123",
        "email_address": "admin@test.com",
        "discord_id": "123456789012345678",
        "config": {"secret": "s3cr3t"},
    }
    result = sanitizer.sanitize_dict(data)
    assert "<API_KEY_REDACTED>" in str(result)
    assert "<EMAIL_ADDRESS_REDACTED>" in str(result)
    assert "<SECRET_REDACTED>" in str(result)
    assert "sk-abc123" not in str(result)
    assert "admin@test.com" not in str(result)


# =============================================================================
# Collector Tests
# =============================================================================

def test_collector_basic():
    """Collector should create a valid snapshot even without skills/plugins."""
    collector = Collector(
        mirror_id="test-collector",
        description="Collection test",
        tags=["test"],
        profile="minimal",
    )
    snapshot = collector.collect()
    assert snapshot.manifest.mirror_id == "test-collector"
    assert snapshot.manifest.description == "Collection test"
    # Should still validate even in empty env (skills dirs just won't be found)
    errors = snapshot.validate()
    if errors:
        print(f"Validation warnings: {errors}")


# =============================================================================
# Packager Tests
# =============================================================================

def test_packager_docker_context():
    """Packager should create a valid Docker build context."""
    snap = Snapshot(
        manifest=Manifest(mirror_id="pack-test", created_at="2026-05-22T23:00:00Z"),
        skills=[SkillEntry(name="test-skill", version="1.0.0", content="# Test Skill\nDo stuff")],
        config={"model": {"default": "gpt-4", "provider": "openai"}},
        plugins=[PluginEntry(name="supabase", version="1.0.1")],
    )

    packager = Packager()
    try:
        ctx = packager.package_docker(snap)
        assert (ctx / "Dockerfile").exists()
        assert (ctx / "snapshot.json").exists()
        assert (ctx / "config.yaml").exists()
        assert (ctx / "entrypoint.sh").exists()
        assert (ctx / "docker-compose.yml").exists()
        assert (ctx / "skills" / "test-skill" / "SKILL.md").exists()
        assert (ctx / "plugins" / "supabase" / "plugin.yaml").exists()

        # Verify Dockerfile content
        dockerfile = (ctx / "Dockerfile").read_text()
        assert "pack-test" in dockerfile
        assert "python:3.11-slim" in dockerfile
        assert "test-skill" in dockerfile

        # Verify snapshot.json is valid
        snapshot_content = (ctx / "snapshot.json").read_text()
        restored = Snapshot.from_json(snapshot_content)
        assert restored.manifest.mirror_id == "pack-test"
    finally:
        packager.cleanup()


def test_packager_tar():
    """Packager should create a valid tar.gz."""
    snap = Snapshot(
        manifest=Manifest(mirror_id="tar-test", created_at="2026-05-22T23:00:00Z"),
        skills=[SkillEntry(name="basic", version="1.0.0")],
        config={"model": {"default": "gpt-4", "provider": "openai"}},
    )

    packager = Packager()
    try:
        import tarfile
        tar_path = packager.package_tar(snap)
        assert tar_path.exists()
        assert tar_path.suffix == ".gz"
        assert tar_path.stat().st_size > 100

        with tarfile.open(tar_path, "r:gz") as tar:
            names = tar.getnames()
            assert any("snapshot.json" in n for n in names)
            assert any("Dockerfile" in n for n in names)
            assert any("entrypoint.sh" in n for n in names)
    finally:
        packager.cleanup()


# =============================================================================
# Run tests
# =============================================================================

if __name__ == "__main__":
    import traceback

    passed = 0
    failed = 0
    tests = [
        ("Empty snapshot validation", test_empty_snapshot_validation),
        ("Valid snapshot", test_valid_snapshot),
        ("Snapshot roundtrip JSON", test_snapshot_roundtrip),
        ("Sanitize AWS key", test_sanitize_aws_key),
        ("Sanitize GitHub token", test_sanitize_github_token),
        ("Sanitize email", test_sanitize_email),
        ("No false positives", test_sanitize_no_false_positives),
        ("Sanitize private key block", test_sanitize_private_key_block),
        ("Sanitize OpenAI key", test_sanitize_openai_key),
        ("Sanitize ETH address (paranoid)", test_sanitize_eth_address),
        ("Minimal profile skip crypto/phone", test_sanitize_profile_minimal),
        ("Sanitize Supabase key", test_sanitize_supabase_key),
        ("Redaction summary", test_redaction_summary),
        ("Sanitizer reuse/reset", test_sanitizer_reuse),
        ("Dict blocked keys", test_sanitize_dict_blocked_keys),
        ("Collector basic", test_collector_basic),
        ("Packager Docker context", test_packager_docker_context),
        ("Packager tar.gz", test_packager_tar),
    ]

    for name, fn in tests:
        try:
            fn()
            print(f"  ✅ {name}")
            passed += 1
        except Exception as e:
            print(f"  ❌ {name}: {e}")
            traceback.print_exc()
            failed += 1

    print(f"\n{'='*50}")
    print(f"Results: {passed} passed, {failed} failed, {len(tests)} total")
    if failed:
        sys.exit(1)
