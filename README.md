<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/asalvarrey/Hermes-Mirroring/main/assets/logo-dark.svg">
    <img src="https://raw.githubusercontent.com/asalvarrey/Hermes-Mirroring/main/assets/logo-light.svg" alt="Hermes Mirror" width="480">
  </picture>
</p>

<p align="center">
  <b>🪞 Sub-Agent Mirroring in One Click</b><br>
  Snapshot, sanitize, package, and deploy clones of your Hermes Agent — skills, config, plugins, and vector memory included
</p>

<p align="center">
  <a href="#-what-is-this"><img src="https://img.shields.io/badge/features-6_E2E_blue?style=flat-square" alt="Features"></a>
  <a href="#-quick-start"><img src="https://img.shields.io/badge/start-30_seconds-green?style=flat-square" alt="30s"></a>
  <a href="#-sanitization-profiles"><img src="https://img.shields.io/badge/profiles-4-purple?style=flat-square" alt="Profiles"></a>
  <a href="tests.py"><img src="https://img.shields.io/badge/tests-18_✓-green?style=flat-square" alt="Tests"></a>
  <a href="https://github.com/asalvarrey/Hermes-Mirroring/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-MIT-purple?style=flat-square" alt="License"></a>
  <a href="https://hermes-agent.nousresearch.com"><img src="https://img.shields.io/badge/for-Hermes_Agent-orange?style=flat-square" alt="Hermes"></a>
  <a href="https://buymeacoffee.com/asalvarrey"><img src="https://img.shields.io/badge/donate-☕_Buy_me_a_coffee-FFDD00?style=flat-square" alt="Buy me a coffee"></a>
</p>

https://github.com/user-attachments/assets/f7764458-9900-40be-856f-4e27dd04faa3

---

## 🧠 What is this?

**Hermes Mirror** turns your Hermes Agent into a **self-replicating platform**. With one command, you can:

> *"Clónate a ti mismo, borra tus datos personales, añade estas credenciales y despliega este nuevo agente en el VPS de mi socio"*

It snapshots everything that makes your agent unique — **skills, configuration, plugins, and even vector memory** — runs it through a **built-in privacy sanitizer**, and packages it as a ready-to-deploy Docker container or VPS artifact.

### Why?

| Problem | Solution |
|---|---|
| 🤯 You tuned Hermes perfectly for finance/DevOps/SAP | 🪞 **Mirror it** — keep the original, deploy a specialist clone |
| 😬 Can't share your agent because of PII/API keys | 🔒 **Built-in sanitizer** — 4 profiles strip secrets automatically |
| 🐢 Setting up a new Hermes from scratch takes hours | ⚡ **One command** — snapshot, deploy, done |
| 🌍 Need an agent for a client but can't give them your config | 📦 **Self-contained artifact** — Docker image or tar.gz |
| 🧠 Clone has no memory of who it is | 💾 **Memory export** — Supabase → SQL → restore on target |

---

## ✨ Features

| # | Feature | Status |
|---|---|---|
| 1 | 🧬 **Full-agent snapshot** — skills, config, plugins, personality | ✅ |
| 2 | 🔒 **Privacy sanitizer** — 36+ regex patterns, 4 profiles (standard/minimal/paranoid/devops) | ✅ |
| 3 | 💾 **Memory export** — Supabase → sanitized SQL/JSON → restore on target | ✅ |
| 4 | 🐳 **Docker deploy** — builds image, runs container, health check | ✅ |
| 5 | ☁️ **VPS deploy** — scp + ssh + docker-compose up in one shot | ✅ |
| 6 | 🏷️ **Snapshot registry** — list, inspect, delete saved mirrors | ✅ |

### Coming in v2.0

- 🔮 **Embedding-based PII detection** (sentence-transformers) — catches secrets no regex can find
- 🔄 **Two-way sync** — merge divergent clones back into the original
- 📊 **Web dashboard** — visual snapshot browser + one-click deploy

---

## 🧬 Architecture

```
┌───────────────────────────────────────────────────────────────────────┐
│                         Hermes Mirror Plugin                          │
│                                                                       │
│  ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────────────┐   │
│  │Collector │──→│Sanitizer │──→│ Packager │──→│    Deployer      │   │
│  │          │   │          │   │          │   │                  │   │
│  │• skills  │   │• 36 regex│   │• Docker  │   │• docker run      │   │
│  │• config  │   │• 4 perf. │   │• tar.gz  │   │• docker compose  │   │
│  │• plugins │   │• entropy │   │• SQL bdl │   │• scp + ssh + up  │   │
│  │• memory  │   │• key blk │   │          │   │                  │   │
│  └────┬─────┘   └──────────┘   └────┬─────┘   └────────┬─────────┘   │
│       │                             │                   │             │
│       └──────────┬──────────────────┘                   │             │
│                  ↓                                      ↓             │
│          snapshot.json +                          Docker container    │
│          memory_restore.sql                        or VPS instance    │
└───────────────────────────────────────────────────────────────────────┘
```

### The Flow

```
"Clónate a ti mismo para finanzas"
         │
         ▼
┌─────────────────────────────────┐
│  hermes mirror create           │
│  hermes-finance-v2              │
│  --profile=paranoid             │
│  --include-memory               │
└─────────────┬───────────────────┘
              │
              ▼
┌─────────────────────────────────────────────────────┐
│  ✅ Snapshot created:                                │
│                                                     │
│  📄 ~/.hermes/mirrors/hermes-finance-v2/            │
│     ├── snapshot.json          ← manifest + skills  │
│     ├── memory_restore.sql     ← sanitized memory   │
│     ├── memory_export.json     ← portable JSON      │
│     └── redaction_log.txt      ← what was scrubbed  │
│                                                     │
│  🔒 12 items redacted:                              │
│     - aws_access_key: 2                             │
│     - github_token: 3                               │
│     - email: 4                                      │
│     - supabase_key: 3                               │
└──────────────────────┬──────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────┐
│  hermes mirror deploy           │
│  hermes-finance-v2              │
│  --target=docker                │
│  --env-file=~/.hermes/.env      │
└─────────────┬───────────────────┘
              │
              ▼
┌─────────────────────────────────────────────────────┐
│  🚀 Deploying:                                      │
│                                                     │
│  📦 Docker build context ready                      │
│  🔨 Building image: hermes-finance-v2               │
│                                                     │
│  ✅ Container started!                              │
│     🆔  a1b2c3d4e5f6                               │
│     📡  Port: 8000                                  │
│     🧠  Memory restored: 47 entries                 │
│                                                     │
│  📋 Logs: docker logs -f hermes-finance-v2          │
└─────────────────────────────────────────────────────┘
```

---

## 🚀 Quick Start

### Installation

```bash
git clone https://github.com/asalvarrey/Hermes-Mirroring.git
cd Hermes-Mirroring

# The CLI is ready to use — no pip install needed
chmod +x hermes-mirror
```

### Create a Mirror Snapshot

```bash
./hermes-mirror create hermes-finance-v2 \
  --description="Financial analyst — S/4HANA specialist" \
  --tags=finance,sap,production \
  --profile=paranoid
```

```
🪞  Creating mirror snapshot: hermes-finance-v2
📋  Profile: paranoid
🧠  Skills: scanning...
🔌  Plugins: scanning...
🔒  Sanitizer: active (paranoid mode)

🔒 12 items redacted:
   - aws_access_key: 2
   - github_token: 3
   - email: 4
   - supabase_key: 3

✅  Mirror snapshot created!
   📄  ~/.hermes/mirrors/hermes-finance-v2/snapshot.json
   🧠  7 skills
   🔌  2 plugins
```

### Inspect Before Deploying

```bash
./hermes-mirror inspect hermes-finance-v2
```

```json
{
  "manifest": {
    "mirror_id": "hermes-finance-v2",
    "created_at": "2026-05-23T01:30:00Z",
    "description": "Financial analyst — S/4HANA specialist"
  },
  "skills": [
    {"name": "youtube-content", "version": "1.2.0"},
    {"name": "github-pr-workflow", "version": "1.0.0"},
    {"name": "systematic-debugging", "version": "2.0.0"}
  ],
  "plugins": [
    {"name": "supabase", "version": "1.0.1", "enabled": true}
  ],
  "valid": true
}
```

### Deploy to Docker

```bash
# Deploy locally
./hermes-mirror deploy hermes-finance-v2 \
  --target=docker \
  --env-file=~/.hermes/.env

# Or deploy to VPS
./hermes-mirror deploy hermes-finance-v2 \
  --target=vps \
  --ssh-host=192.168.1.100 \
  --ssh-user=root \
  --env-file=~/client-finance.env
```

### Manage Snapshots

```bash
# List all mirrors
./hermes-mirror list

# Delete a mirror
./hermes-mirror delete hermes-finance-v2
```

---

## 🔒 Sanitization Profiles

Every snapshot passes through the sanitizer. Choose your profile:

| Profile | What it catches | What it skips | Use case |
|---|---|---|---|
| **`standard`** | API keys, tokens, SSH keys, emails, crypto wallets, DB URLs, JWT | Phone numbers, generic IPs | General purpose |
| **`minimal`** | API keys, tokens, SSH keys | Emails, phones, crypto, IPs | Fast clones, trusted networks |
| **`paranoid`** | Everything + entropy-based detection | Nothing | Client deployments, public sharing |
| **`devops`** | AWS, GitHub, Supabase, SSH, infra keys | Emails, crypto, personal PII | Infrastructure-only clones |

### What gets caught (36+ patterns)

```
🔑 AWS Access Key       🔑 GitHub Token (ghp_)      🔑 OpenAI API Key (sk-)
🔑 Anthropic Key        🔑 Supabase JWT             🔑 SSH Private Key
🔑 Google API Key       🔑 Slack Token              🔑 Discord Token
🔑 Telegram Bot Token   🔑 Stripe Live/Test         🔑 Twilio Key
🔑 SendGrid Key         🔑 Mailgun Key              🔑 Heroku API Key
🔑 JWT Token            🔑 Private Key (RSA/DSA/EC)
💳 Ethereum Address     💳 Bitcoin Address          💳 SegWit Address
📧 Email                📞 Phone (US/Intl)
🌐 Internal IP          🌐 Supabase URL             🌐 Ngrok URL
🗄️ DB Connection URL    🗄️ Redis URL
```

---

## 🧪 Tests

```bash
python tests.py
```

```
  ✅ Empty snapshot validation
  ✅ Valid snapshot
  ✅ Snapshot roundtrip JSON
  ✅ Sanitize AWS key
  ✅ Sanitize GitHub token
  ✅ Sanitize email
  ✅ No false positives
  ✅ Sanitize private key block
  ✅ Sanitize OpenAI key
  ✅ Sanitize ETH address (paranoid)
  ✅ Minimal profile skip crypto/phone
  ✅ Sanitize Supabase key
  ✅ Redaction summary
  ✅ Sanitizer reuse/reset
  ✅ Dict blocked keys
  ✅ Collector basic
  ✅ Packager Docker context
  ✅ Packager tar.gz

==================================================
Results: 18 passed, 0 failed, 18 total
```

---

## 🔮 Roadmap

- **v1.0.x** — Current: snapshot + sanitize + docker/VPS deploy
- **v1.1.0** — Memory restore automation on target
- **v1.2.0** — Interactive deploy wizard (ask for credentials at deploy time)
- **v2.0.0** — Embedding-based PII detection + two-way sync + dashboard

---

## 🛡️ Privacy First

This plugin was built with **Privacy by Design**:

- **Credentials NEVER leave the source machine** — only env-var names are recorded
- **Sanitizer runs before packaging** — nothing sensitive reaches the snapshot file
- **Redaction is auditable** — `redaction_log.txt` shows what was caught (never the actual values)
- **No telemetry** — zero calls home, zero analytics, zero tracking
- **Open source (MIT)** — audit the code yourself

---

## 🤝 Contributing

PRs welcome! Areas that need love:
- More detection patterns (SAP credentials, anyone?)
- Additional deployment targets (Kubernetes, Nomad, systemd)
- Web UI for snapshot management

---

## 📄 License

MIT — do what you want, just don't blame us.

---

<p align="center">
  Built with 🔥 by <a href="https://salvarrey.tech">Antonio Salvarrey</a><br>
  Senior SAP Basis Manager & Cloud Architect · 22+ years engineering stability<br><br>
  <a href="https://buymeacoffee.com/asalvarrey"><img src="https://img.shields.io/badge/☕-Buy_me_a_coffee-FFDD00?style=flat-square&logo=buymeacoffee&logoColor=black" alt="Buy me a coffee"></a>
</p>
