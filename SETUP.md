# Explainer Bot — Setup

Get from a fresh `git clone` to a running server, step by step, with a
verification checkpoint after each stage so you know it worked before
moving on.

> **Already set up and just want to *use* it?** See
> [USER_GUIDE.md](USER_GUIDE.md) (non-technical) or
> [USER_MANUAL.md](USER_MANUAL.md) (full reference).
> **Want the architecture?** [SYSTEM_DESIGN.md](SYSTEM_DESIGN.md).

---

## Contents

- [Prerequisites](#prerequisites)
- [Step 1 — Clone](#step-1--clone)
- [Step 2 — System tools (ffmpeg)](#step-2--system-tools-ffmpeg)
- [Step 3 — Python environment](#step-3--python-environment)
- [Step 4 — Headless browser](#step-4--headless-browser)
- [Step 5 — Pick an LLM backend](#step-5--pick-an-llm-backend)
- [Step 6 — (Optional) a better TTS voice](#step-6--optional-a-better-tts-voice)
- [Step 7 — Verify the whole thing](#step-7--verify-the-whole-thing)
- [Step 8 — Run it](#step-8--run-it)
- [Updating later](#updating-later)
- [Uninstall / cleanup](#uninstall--cleanup)
- [Troubleshooting](#troubleshooting)

---

## Prerequisites

You need these installed before you start. Versions shown are minimums
that are known to work.

| Tool       | Why                          | Install / check                                              |
| ---------- | ---------------------------- | ------------------------------------------------------------ |
| **macOS**  | `say` TTS, `open`            | Linux works too — see notes in [Step 6](#step-6--optional-a-better-tts-voice) and [SYSTEM_DESIGN §10.9](SYSTEM_DESIGN.md) |
| **Homebrew** | installs ffmpeg, ollama    | `brew --version` · install: <https://brew.sh>                |
| **git**    | clone the repo               | `git --version`                                              |
| **uv**     | Python env + deps            | `uv --version` · install: `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| **Python 3.11+** | runtime                | `uv` will fetch it if you don't have it                      |
| **One LLM source** | the bot's brain        | Decided in [Step 5](#step-5--pick-an-llm-backend) — don't worry yet |

Quick check that the basics are present:

```bash
brew --version && git --version && uv --version
```

If any of those error, install it before continuing.

---

## Step 1 — Clone

```bash
git clone https://github.com/mahadevaiahrashmi/explainer-bot.git
cd explainer-bot
```

**Checkpoint:** `ls` shows `app.py`, `pipeline.py`, `pyproject.toml`,
`templates/`, etc.

---

## Step 2 — System tools (ffmpeg)

ffmpeg + ffprobe assemble the video. They're not Python packages, so
install them with Homebrew.

```bash
brew install ffmpeg
```

**Checkpoint:**

```bash
ffmpeg -version | head -1 && ffprobe -version | head -1
```

Both should print a version line.

---

## Step 3 — Python environment

`uv` creates an isolated virtual environment and installs every Python
dependency from the lockfile.

```bash
uv venv --python 3.11
uv sync
```

`uv sync` reads `pyproject.toml` + `uv.lock` and installs FastAPI,
Uvicorn, Playwright, Pydantic, httpx, the `llm` CLI, etc.

**Checkpoint:**

```bash
.venv/bin/python -c "import fastapi, playwright, httpx, llm; print('python deps OK')"
```

---

## Step 4 — Headless browser

Playwright renders each slide's HTML and screenshots it. It needs a
Chromium binary, downloaded once.

```bash
.venv/bin/playwright install chromium
```

This pulls ~150 MB into `~/Library/Caches/ms-playwright/`.

**Checkpoint:**

```bash
.venv/bin/python -c "
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    b = p.chromium.launch(); b.close()
print('chromium OK')"
```

---

## Step 5 — Pick an LLM backend

The bot needs an AI to write scripts and design slides. Pick **one** of
the five. `BACKEND=` (env var) selects it; if unset, the bot
auto-detects in the order below.

> Full detail (per-backend caveats, model lists) is in
> [USER_MANUAL.md → Backend configuration](USER_MANUAL.md#backend-configuration).
> This is the fastest path to a working setup for each.

### Option A — `claude_cli` (Claude Code subscription) — easiest if you have it

```bash
claude --version    # if this works, you're done — the bot auto-detects it
```

No API key, no per-call cost. Uses your existing Claude Code login.

### Option B — `ollama` (free, local, no internet)

```bash
brew install ollama
brew services start ollama          # daemon; auto-starts on login afterwards
ollama pull llama3.2                 # ~2 GB; or qwen2.5:14b (~8.5 GB) for better quality
```

Then either `export BACKEND=ollama` or let it auto-detect.

### Option C — `codex_cli` (OpenAI ChatGPT Plus / Pro)

```bash
npm install -g @openai/codex
codex login                          # browser flow against your ChatGPT account
```

### Option D — `gemini_cli` (Google AI Pro / free tier)

```bash
npm install -g @google/gemini-cli
gemini auth                          # or: export GEMINI_API_KEY=...
```

### Option E — `llm` (any cloud API key)

```bash
.venv/bin/llm keys set openai        # or claude / gemini / deepseek / openrouter
export BACKEND=llm
export LLM_MODEL=gpt-4.1             # or claude-sonnet-4-5, gemini-2.0-flash, etc.
```

For DeepSeek / Qwen via OpenRouter, see
[USER_MANUAL.md → Other providers](USER_MANUAL.md#backend-5--llm-cloud-api-key--anthropic--openai--gemini--).

**Checkpoint** (works for whichever backend you set up):

```bash
.venv/bin/python -c "import pipeline, asyncio; print('backend =', pipeline.get_backend()); \
    print('reply:', asyncio.run(pipeline.llm_call('Reply with exactly OK.', 'go')))"
```

You should see your backend name and `reply: OK`.

---

## Step 6 — (Optional) a better TTS voice

This step is **optional** — by default the bot narrates with macOS
`say`, which needs no setup. Skip to Step 7 if you'll record your own
voice or are fine with the built-in voice for now.

`TTS_ENGINE=` picks the voice engine. Options:

### Supertonic (open-source, recommended — auto-downloads its model)

```bash
.venv/bin/uv add supertonic          # first auto-narrate downloads ~260 MB of models
export TTS_ENGINE=supertonic
```

### Piper (open-source, needs a voice file)

```bash
pipx install piper-tts
mkdir -p ~/piper-voices && cd ~/piper-voices
curl -L -O https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx
curl -L -O https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx.json
cd -
export TTS_ENGINE=piper
```

### eSpeak-NG (cross-platform fallback, very robotic)

```bash
brew install espeak-ng
export TTS_ENGINE=espeak
```

Full TTS details (voices, languages, costs) are in
[USER_MANUAL.md → Text-to-speech engines](USER_MANUAL.md#text-to-speech-engines-tts_engine).

---

## Step 7 — Verify the whole thing

Run the smoke test — it drives the entire pipeline (script → slides →
screenshots → cue video → audio → final MP4) using `say` as a stand-in
voice, so it runs unattended.

```bash
.venv/bin/python smoke_test.py
```

It prints progress through 4 stages and ends with a line like:

```
Done: /Users/.../jobs/<id>/video.mp4  (1873557 bytes)
```

**If that line appears, your setup is complete and working.** Open the
file to confirm:

```bash
open jobs/<id>/video.mp4
```

> The smoke test truncates to 2 slides for speed and uses `say` for
> audio regardless of `TTS_ENGINE`. To test your chosen TTS engine
> end-to-end, run a real one-shot (Step 8) instead.

---

## Step 8 — Run it

### Web UI (recommended)

```bash
.venv/bin/uvicorn app:app --reload --port 8000
```

Open <http://localhost:8000>. Type rough points → Draft script → edit
slides → build cue → record or auto-narrate → build final video.

### Terminal UI

```bash
.venv/bin/python cli.py
```

### Hands-off one-shot (no clicks, no recording)

```bash
echo "What is recursion?
- a function that calls itself
- needs a base case
- matryoshka analogy
." | .venv/bin/python cli.py --auto-narrate
```

Pin a backend / voice with env vars on any of these:

```bash
echo "your rough points ." | \
  BACKEND=ollama TTS_ENGINE=supertonic .venv/bin/python cli.py --auto-narrate
```

---

## Updating later

```bash
cd explainer-bot
git pull
uv sync                              # pick up any new Python deps
.venv/bin/playwright install chromium   # in case the pinned Chromium changed
```

---

## Uninstall / cleanup

Everything the bot creates lives in two places:

```bash
# Generated videos / jobs (safe to delete anytime):
rm -rf jobs/

# The whole project + venv:
cd .. && rm -rf explainer-bot
```

Stop background services if you started them:

```bash
lsof -ti :8000 | xargs kill 2>/dev/null   # web server
brew services stop ollama                  # ollama daemon
```

System tools installed via Homebrew (`ffmpeg`, `ollama`, `espeak-ng`)
stay until you `brew uninstall` them. Playwright's Chromium lives in
`~/Library/Caches/ms-playwright/` (delete to reclaim ~150 MB).

---

## Troubleshooting

### `uv: command not found`

Install uv: `curl -LsSf https://astral.sh/uv/install.sh | sh`, then open
a new terminal (or `source ~/.zshrc`).

### `ffmpeg: command not found` during a video build

`brew install ffmpeg`. Confirm with `ffmpeg -version`.

### Step 4 chromium check hangs or errors

Re-run `.venv/bin/playwright install chromium`. On Apple Silicon make
sure you're not under Rosetta. If a corporate proxy blocks the
download, set `HTTPS_PROXY` and retry.

### Step 5 checkpoint: "No LLM backend available"

You haven't set up any of the five backends. Re-do
[Step 5](#step-5--pick-an-llm-backend) for at least one. The error
message lists install commands for all of them.

### `claude CLI timed out` / `llm CLI failed: No key found`

The backend is installed but not authenticated. For `claude_cli`, run
`claude` once interactively to log in. For `llm`, run
`.venv/bin/llm keys set <provider>`.

### Ollama: "unreachable"

`brew services start ollama` (or `ollama serve` in another terminal),
then `ollama pull <model>` if the model isn't downloaded.

### Reasoning models (DeepSeek-R1, QwQ) time out

They "think" for minutes. Raise the per-call patience:
`export LLM_TIMEOUT_S=900` (default is 600). See
[USER_MANUAL.md](USER_MANUAL.md) for which models are reasoning models.

### Smoke test fails partway

Read the last progress line — it tells you which stage failed (script /
slides / screenshot / audio / assemble). Match it to the relevant step
above. A malformed-JSON error usually means a small local model; try a
bigger one (`qwen2.5:14b`) or a different backend.

### Something else

Deeper troubleshooting is in
[USER_MANUAL.md → Troubleshooting](USER_MANUAL.md#troubleshooting) and
[TESTING.md → Bug-reporting workflow](TESTING.md).
