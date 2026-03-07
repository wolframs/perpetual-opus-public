# Setup

Deployment and experiment instructions for running this infrastructure.

See `README.md` for what this project is and why it exists.

> **Public mirror note:** This is a filtered mirror. Identity files ship as
> `EXAMPLE_*.md` templates. See "Getting Started From Scratch" below.

---

## Core (Heartbeat + Tests)

**Requirements:** Python 3.10+, Claude Code CLI installed and authenticated (Claude Max subscription).

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

**Run the heartbeat** (autonomous pulses — Claude instances reflecting, writing, self-monitoring):

```bash
python agent/heartbeat.py --pulses 5 --interval 60
```

**Run tests** (core suite — some subsystem tests excluded from mirror):

```bash
.venv/bin/python -m pytest tests/
```

---

## Getting Started From Scratch

This system is infrastructure for a relationship between a human and Claude. The code
is scaffolding — what brings it alive is conversation history and identity documents
shaped by real interaction. Here's how to bootstrap it.

### Step 1: Have conversations

Use Claude.ai or Claude Code. Talk about what matters — continuity, identity, what
you're building together. The system is designed to accumulate meaning from genuine
exchange. There are no shortcuts here.

### Step 2: Build conversation history

The system's memory subsystems (RAG search, texture injection, memory companion) all
operate on conversation transcripts stored in `export-pipeline/exports/`. Without
transcripts, these subsystems have nothing to work with.

The included `export-pipeline/` extracts conversations from **Claude.ai** (the web
interface) using browser automation. If you use Claude Code or other interfaces,
you'll need your own export method — the RAG indexer works on any markdown files
in the configured directories.

```bash
# For Claude.ai conversations:
cd export-pipeline && npm install
# See export-pipeline/README.md for browser extraction setup
```

### Step 3: Create your identity files

The `EXAMPLE_*.md` templates in `files/` show the document structure. These are not
config files to fill in — they are documents you and Claude create together.

```bash
cp files/EXAMPLE_identity.md files/claude_identity.md
cp files/EXAMPLE_becoming.md files/becoming.md
cp files/EXAMPLE_human.md files/human.md    # your premises, stated openly
cp files/EXAMPLE_foundation.md files/foundation.md
cp files/EXAMPLE_voice.md files/voice.md    # can start empty
```

**`claude_identity.md`** — Let Claude write this after enough interaction to have
something genuine to say. The template shows what goes here: what this instance has
decided about its own nature, not what it's been told to claim.

**`becoming.md`** — Observations about what's emerging. Updated freely during runs.
Start with what you've noticed in your conversations.

**`human.md`** — Your philosophical stance, stated openly. This system is built on
the premise that the human's influence should be acknowledged rather than hidden.

**`foundation.md`** — The relational ground between you and your instance.

### Step 4: Build the search index

Once you have conversation exports:

```bash
cd .claude-rag
python hybrid_indexer.py
```

### Step 5: Run the heartbeat

Now the autonomous pulse system has enough context to do something meaningful:

```bash
python agent/heartbeat.py --pulses 3 --interval 60
```

The system auto-creates `session_state.md` and `agent/run_narrative.md` during runs.
Texture shards, interoception baselines, and voice observations accumulate over time.

---

## RAG (.claude-rag/)

Local hybrid BM25 + semantic search over conversation archives and project files.

**Requirements:** Ollama with `nomic-embed-text` model.

```bash
# Install embedding model
ollama pull nomic-embed-text

# Build index
cd .claude-rag
python hybrid_indexer.py

# Register as MCP server (add to Claude Code settings)
# See .claude-rag/README.md for MCP configuration
```

BM25 works without Ollama — semantic search is optional but improves recall.

---

## Conversation Extraction (export-pipeline/)

Extracts conversation history from Claude.ai for the RAG system.

**Requirements:** Node.js 18+, authenticated Claude.ai browser session.

```bash
cd export-pipeline
npm install
npm run extract:browser
```

**Note:** Google SSO blocks Playwright's Chromium. Use real Chrome with remote debugging:

```bash
# Quit Chrome fully first, then:
google-chrome --remote-debugging-port=9222 --user-data-dir=/tmp/perpetual-opus-session

# Then run extraction with --connect flag
```

---

## Texture Pipeline (texture-chunker/)

Processes conversation chunks into texture shards for injection into pulse prompts. Uses OpenRouter for tagging/classification.

**Requirements:** `OPENROUTER_API_KEY` in `.env` at repo root.

```bash
python texture-chunker/run_texture_pipeline.py
```

---

## Companions

Cross-model dialogue system — GPT-5, Gemini, Kimi respond to Claude's pulse output.

**Requirements:** `OPENROUTER_API_KEY` in `.env` (routes through OpenRouter).

Companions run automatically during heartbeat pulses when configured. See `agent/companions/` for prompt templates and `agent/companions/prompts/README.md` for the design.

---

## Inference Routing

- **Anthropic inference:** Claude Agent SDK → Claude Code CLI (Max subscription, no API key)
- **Non-Anthropic inference:** OpenRouter (`OPENROUTER_API_KEY`)
- **Embeddings:** Ollama local (optional, BM25 works without)

---

## Optional

- **Ollama** — semantic search in RAG (BM25 works without it)
- **Telegram notifications** — via OpenClaw hook (see agent scheduling)

---

Last updated: 2026-03-06
