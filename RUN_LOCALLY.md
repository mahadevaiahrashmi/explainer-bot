# Run Locally — Quick Start

The shortest path from clone to a running server. Just the commands.
For checkpoints, per-backend detail, and troubleshooting, see
**[SETUP.md](SETUP.md)**.

> **Prereqs:** macOS + [Homebrew](https://brew.sh), `git`, and
> [`uv`](https://astral.sh/uv) (`curl -LsSf https://astral.sh/uv/install.sh | sh`).

---

## 1. Set up (once)

```bash
git clone https://github.com/mahadevaiahrashmi/explainer-bot.git
cd explainer-bot

brew install ffmpeg                       # video assembly
uv venv --python 3.11                     # isolated env
uv sync                                   # install Python deps
.venv/bin/playwright install chromium     # headless browser for slide shots
```

## 2. Give it a brain (pick ONE backend)

The bot auto-detects in this order; setting `BACKEND=` forces a choice.

```bash
# A) Claude Code subscription — no key, no cost. Easiest if you have it.
claude --version                          # if this works, you're done

# B) Ollama — free, local, offline.
brew install ollama && brew services start ollama
ollama pull llama3.2                      # or qwen2.5:14b for better quality
export BACKEND=ollama

# C) ChatGPT Plus/Pro
npm install -g @openai/codex && codex login
export BACKEND=codex_cli

# D) Google AI Pro / free
npm install -g @google/gemini-cli && gemini auth
export BACKEND=gemini_cli

# E) Any cloud API key (OpenAI, Anthropic, Gemini, DeepSeek, OpenRouter…)
.venv/bin/llm keys set openai
export BACKEND=llm LLM_MODEL=gpt-4.1
```

## 3. Run it

```bash
# Web UI (recommended) → open http://localhost:8000
.venv/bin/uvicorn app:app --reload --port 8000

# Terminal UI
.venv/bin/python cli.py

# Hands-off one-shot (no clicks, auto-narrated)
echo "What is recursion?
- a function that calls itself
- needs a base case
- matryoshka doll analogy
." | .venv/bin/python cli.py --auto-narrate
```

Pin a backend / voice inline on any run:

```bash
echo "your points ." | \
  BACKEND=ollama TTS_ENGINE=supertonic .venv/bin/python cli.py --auto-narrate
```

## 4. Stop it

```bash
lsof -ti :8000 | xargs kill 2>/dev/null   # web server
brew services stop ollama                  # ollama daemon (if started)
```

---

**Want more?** Verification checkpoints, optional neural TTS voices, and a
full troubleshooting table are in **[SETUP.md](SETUP.md)**. Day-to-day usage
is in [USER_GUIDE.md](USER_GUIDE.md) (plain English) and
[USER_MANUAL.md](USER_MANUAL.md) (full reference).
