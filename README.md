# 🪞 Hermes Mirror — Sub-Agent Mirroring in One Click

**Snapshot, sanitize, package, and deploy clones of your Hermes Agent.**

Clone yourself — skills, config, plugins, and even vector memory — sanitize PII, and deploy as a new Docker container or VPS instance. Perfect for spinning up specialized agent instances: financial analyst, DevOps assistant, client-facing support, etc.

## 🧬 The Flow

```
┌─────────────────────────────────────────────────────────────────┐
│  "Clónate a ti mismo para finanzas"                             │
│                          ↓                                      │
│               hermes mirror create hermes-finance               │
│                          ↓                                      │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │ Collector: skills, config, plugins, memory, vault       │    │
│  │ Sanitizer: 🔒 PII → <PLACEHOLDER>                       │    │
│  └────────────────────────┬────────────────────────────────┘    │
│                           ↓                                     │
│               snapshot.json + memory_restore.sql                 │
│                           ↓                                     │
│               hermes mirror deploy hermes-finance                │
│                           ↓                                     │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │ Docker build → docker run  o  VPS: scp + compose up     │    │
│  │ Restore memory SQL en target                             │    │
│  └─────────────────────────────────────────────────────────┘    │
│                           ↓                                     │
│              🎉 Hermes B born — with skills,                     │
│                 personality AND memory of A                      │
└─────────────────────────────────────────────────────────────────┘
```

## 📦 Components

| Module | What it does |
|--------|-------------|
| `mirror/schema.py` | Canonical snapshot JSON schema (versioned) |
| `mirror/collector.py` | Gathers skills, config, plugins, memory |
| `mirror/sanitizer.py` | 36+ regex patterns, 4 profiles (standard/minimal/paranoid/devops) |
| `mirror/memory_extractor.py` | Extracts memory from Supabase → SQLite → gracefully empty |
| `mirror/packager.py` | Builds Docker context or standalone tar.gz |
| `mirror/deployer.py` | Deploys to local Docker or remote VPS via SSH |

## 🔒 Sanitization Profiles

| Profile | Scope |
|---------|-------|
| `standard` | API keys, tokens, SSH keys, emails, crypto wallets |
| `minimal` | API keys + tokens only (no emails, crypto, phones) |
| `paranoid` | Everything + entropy-based secret detection |
| `devops` | Cloud/infra keys only (AWS, GitHub, Supabase, SSH) |

## 🚀 Quick Start

```bash
# 1. Create a mirror snapshot
./hermes-mirror create hermes-finance-v2 \
  --description="Financial analyst agent clone" \
  --profile=standard

# 2. Inspect it
./hermes-mirror inspect hermes-finance-v2

# 3. Deploy to Docker
./hermes-mirror deploy hermes-finance-v2 --target=docker

# 4. Or deploy to VPS
./hermes-mirror deploy hermes-finance-v2 \
  --target=vps \
  --ssh-host=192.168.1.100 \
  --env-file=~/.hermes/.env

# 5. List all snapshots
./hermes-mirror list
```

## 🧪 Tests

```bash
python tests.py
# → 18/18 passed ✅
```

## 📄 License

MIT — do what you want, just don't blame us.

---

Built by [Antonio Salvarrey](https://salvarrey.tech) · ☕ [Buy me a coffee](https://buymeacoffee.com/asalvarrey)
