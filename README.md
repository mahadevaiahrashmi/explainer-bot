# Explainer Bot

Turn rough points into a narrated explainer video — recorded **in your own
voice**. Inspired by the [3Blue1Brown](https://www.youtube.com/watch?v=jx6FevmKJGg)
style: short slides, vivid analogies, a genuine sense of wonder.

It runs in three stages:

```
  rough points ─► script + critique ─► slide HTML (one per segment)
                                              │
                       (preview each slide in an iframe, edit the HTML
                        in a textarea, re-render to update the PNG)
                                              │
                                              ▼
                                       cue video + script.txt
                                              │
                          (you record audio for each slide,
                           drop the files into the audio/ folder)
                                              │
                                              ▼
                                        final video.mp4
```

Both stages are available from a **web UI** and a **terminal UI**.

The bot needs an LLM to write scripts and design slides. Pick any one of
**three backends** — set `BACKEND` to choose, or let it auto-detect:

1. **`claude_cli`** — your Claude Code subscription. No API key, no per-call
   cost. Auto-selected if `claude` is on `PATH`. ✨ Recommended if you already
   have Claude Code.
2. **`ollama`** — fully local, free, no internet. Auto-selected if an Ollama
   server is reachable. Quality varies by model.
3. **`llm`** — provider-agnostic CLI; works with Anthropic, OpenAI, Gemini,
   Mistral, Groq, etc. Requires an API key from one provider. Auto-selected
   as a last resort.

See [Backend configuration](#backend-configuration) below for setup of each.

---

## Tech stack

| Layer                | Choice                                    | Why                                                                                          |
| -------------------- | ----------------------------------------- | -------------------------------------------------------------------------------------------- |
| Language             | **Python 3.11**                           | One language for pipeline, server, and CLI. 3.10+ for modern typing (`X \| Y`, `dict[str, …]`). |
| Package manager      | **uv**                                    | Fast resolver, lockfile, isolated venv in one tool.                                          |
| Web framework        | **FastAPI** + **Uvicorn**                 | Async-native, zero-boilerplate JSON I/O, runs the long-poll endpoints comfortably.           |
| Request validation   | **Pydantic v2**                           | Schema for every request/response; built into FastAPI.                                       |
| File uploads         | **python-multipart**                      | FastAPI's required dep for `multipart/form-data`; used for per-slide audio uploads.          |
| Web UI               | **Vanilla HTML + CSS + JS** (no build)    | Single `templates/chat.html`; deliberately no React/bundler — keeps the surface area small.  |
| Terminal UI          | **stdlib only** (`argparse`, ANSI colours, `subprocess` to `$EDITOR`) | No `rich`/`textual` dep; the TUI is a thin, dependency-free wrapper around the pipeline. |
| LLM (pluggable)      | **3 backends:** `claude_cli` (Claude Code subscription) / `ollama` (free local) / `llm` (provider-agnostic CLI) | Single dispatch in `pipeline.llm_call()`. Auto-detects; set `BACKEND=` to force. Subscription path needs no API key; Ollama needs no internet; `llm` works with Anthropic/OpenAI/Gemini/Groq/... |
| Slide rendering      | **Playwright** + **Chromium (headless)**  | Claude writes standalone HTML; the browser screenshots it. Deterministic and offline.        |
| Voice (optional)     | **macOS `say`**                           | Built-in TTS for the auto-narrate fallback. No cloud TTS bills; primary flow is user-recorded human voice. |
| Video assembly       | **ffmpeg** + **ffprobe**                  | Per-slide clip (image + audio) → concat → MP4. No libass / `subtitles=` filter, so stock Homebrew ffmpeg works. |
| Output format        | **MP4** (H.264 video, AAC stereo audio)   | Universal playback; 1920×1080 @ 30 fps.                                                       |
| Persistence          | **Plain files** under `jobs/<id>/`        | `plan.json`, slide HTML/PNG, audio, cue/final MP4. No database; the disk layout *is* the state model. |
| Process model        | In-process async tasks + on-disk handoff  | `asyncio.create_task` for background work; resumable across server restarts because state is on disk. |
| Dev tooling          | **uv**, **smoke_test.py**                 | `smoke_test.py` drives both pipeline stages end-to-end (uses `say` as stand-in voice) to verify changes. |

External requirements: macOS, Homebrew, ffmpeg, Claude Code (for the
`claude` CLI). Everything else installs via `uv sync` + `playwright
install chromium`. Full dependency table including auth/runtime
requirements lives in [SYSTEM_DESIGN.md §7](SYSTEM_DESIGN.md#7-external-dependencies).

---

## For non-technical readers

### What does it do?

You type a few rough points about an idea you want to explain. About a minute
later you get back:
- A draft script — broken into slide-sized chunks of narration.
- A critique of the script from an AI reviewer who checks that the script is
  understandable to a first-year CS undergrad, uses good analogies, and has a
  sense of wonder.
- A chance to edit anything before slides are built.

Once you approve the script, the bot designs slides for each chunk and
assembles them into a **silent "cue" video** — basically a slideshow with no
audio. It also gives you a printable **script.txt** that tells you, for each
slide, how long to talk and exactly what to say.

You then **record your own voice** — one audio file per slide
(`slide_00.wav`, `slide_01.wav`, …) — and drop those files into the audio
folder the bot shows you. The bot stitches everything together: each slide
stays on screen for exactly as long as your recording for it, and the final
output is an MP4 you can play or share.

### Can the bot speak it for me?

Yes — at the audio step you can click **"Auto-narrate missing slides"**
(or in the CLI, hit `n`) and macOS's built-in `say` voice will fill in any
slide you haven't recorded yourself. There's also **"Auto-narrate
everything (overwrite)"** that replaces *all* slide audio with synthesised
narration in one click, plus a `python cli.py --auto-narrate` flag for
fully unattended end-to-end runs.

That said, real videos in this style — like 3Blue1Brown's — work because
there's a *human* voice with curiosity and pauses behind them. Recording
yourself, even just on a phone, sounds dramatically better than synthesised
speech. The auto-narrate option is mostly useful for previewing the final
shape of the video before you decide which slides to re-record.

### What does it cost?

Depends on the backend you pick:

- **Claude Code subscription** → nothing per video. The bot's script-writing,
  critique, and slide-design calls count against your normal subscription
  allowance, not a paid API account.
- **Ollama (local)** → nothing per video, no internet needed. The cost is in
  your computer's RAM and time — bigger models give better slides but take
  longer.
- **Cloud API key (via `llm`)** → pay per token. A typical 6-slide video is
  ~5 model calls and costs roughly $0.02–$0.05 on Claude Sonnet at current
  pricing, less on smaller models, and the free tiers on Gemini are usually
  enough for occasional use.

---

## For technical readers

> **Doc map:**
> - Install, run, troubleshoot → **[USER_MANUAL.md](USER_MANUAL.md)**.
> - Problem, personas, requirements, success metrics → **[PRD.md](PRD.md)**.
> - UX flows, screens, design system, copy guidelines → **[PRODUCT_DESIGN.md](PRODUCT_DESIGN.md)**.
> - Architectural reference (components, API contracts, sequence
>   diagrams, decision log) → **[SYSTEM_DESIGN.md](SYSTEM_DESIGN.md)**.
> - Testing strategy, UAT checklist, bug-reporting workflow →
>   **[TESTING.md](TESTING.md)**.
> - How the reviewer / critic works → **[docs/reviewer.md](docs/reviewer.md)**.
>
> This section is the quick overview.

### Architecture

```
┌──────────────┐  rough_points      ┌────────────────────────────────────┐
│  Web chat /  │ ─────────────────► │  POST /script                      │
│  TUI (cli.py)│                    │   └─► pipeline.draft_script        │
│              │ ◄── script ─────── │        ├─► claude WRITER           │
│              │     critique       │        ├─► claude AESTHETIC        │
│              │     aesthetic      │        └─► claude CRITIC           │
│  user edits  │                    │                                    │
│  + approves  │                    │                                    │
│              │  segments          │  POST /cue (async background task) │
│              │ ─────────────────► │   └─► pipeline.build_cue           │
│              │                    │        ├─► claude SLIDE × N        │
│              │                    │        ├─► playwright PNG × N      │
│              │                    │        ├─► ffmpeg silent clip × N  │
│              │                    │        └─► concat → cue_video.mp4  │
│              │ ◄── cue_video.mp4 ─┤            + script.txt            │
│              │     script.txt     │            + plan.json (persisted) │
│              │                    │                                    │
│  user records audio                                                     │
│  files locally and uploads ──►   │  POST /jobs/{id}/audio              │
│  (web)  or  drops in audio/ ──►  │  (or just save into audio/ for TUI) │
│                                                                         │
│              │ click finalize  │  POST /jobs/{id}/finalize             │
│              │ ──────────────► │   └─► pipeline.build_final            │
│              │                  │        ├─► ffprobe each user audio   │
│              │                  │        ├─► ffmpeg per-slide clip × N │
│              │                  │        │   (image + audio, len=audio)│
│              │                  │        └─► concat → video.mp4        │
│              │ ◄── video.mp4 ─── │  GET  /jobs/{id}/video              │
└──────────────┘                   └────────────────────────────────────┘
```

### Components

| File                  | What it does                                                       |
| --------------------- | ------------------------------------------------------------------ |
| `pipeline.py`         | Pure-Python pipeline. Two entry points: `build_cue`, `build_final`.|
| `app.py`              | FastAPI — serves the chat UI and the `/script`, `/cue`, `/jobs/*/audio`, `/jobs/*/finalize` endpoints. |
| `cli.py`              | Interactive terminal UI with the same flow as the web UI.          |
| `prompts.py`          | System prompts: writer, critic, slide-designer, aesthetic-picker.  |
| `templates/chat.html` | Single-page chat UI (vanilla JS, no build step).                   |
| `smoke_test.py`       | Drives both pipeline stages end-to-end (uses `say` as stand-in audio). |
| `jobs/{id}/`          | Per-job directory: `plan.json`, `slides/`, `audio/`, `work/`, `cue_video.mp4`, `script.txt`, `video.mp4`. |

### Why two stages?

The previous version of this tool synthesised narration with macOS `say`
and burned it straight into the video. That works, but synthetic narration
is the single biggest quality drop in an otherwise-decent video.

Splitting the build at the audio boundary means:
- The script and slide design are *cheap and re-runnable* — they only cost
  Claude calls.
- Your voice is the only input the final assembly needs. You can re-record
  one slide without redoing anything else (just drop a new
  `slide_NN.<ext>` into the audio folder and re-finalize).
- The cue video itself is silent and uses estimated durations (160 wpm
  default) so you can preview the visuals before recording.

### Why the `claude` CLI instead of the Anthropic SDK?

The Anthropic Python SDK calls `api.anthropic.com` and bills per token
against an API key. The `claude` binary shipped with [Claude Code](https://docs.claude.com/en/docs/claude-code/overview)
authenticates against the user's Claude.ai / Claude Max subscription, so each
call counts against the subscription's allowance instead. For a tool that
makes ~3–6 model calls per video, the CLI's extra startup latency (~2s per
call) is acceptable, and the user pays nothing extra. Swap in the SDK by
editing the single `pipeline.claude()` function.

### Slide rendering

Each segment becomes one standalone HTML document at 1920×1080 with no
external assets (no remote fonts, no remote images). Playwright loads it via
`page.set_content` and screenshots it — deterministic and offline.

### Audio handling

We accept `.wav`, `.mp3`, `.m4a`, `.aac`, `.aiff`, `.flac`, `.ogg`, and
`.opus`. Filename must start with `slide_NN` (zero-padded slide index).
The per-slide clip's duration is `ffprobe`'d from the audio file, so the
slide stays on screen for exactly as long as your recording. Final
assembly is one ffmpeg pass per slide (image + audio + scale to 1920×1080)
then a single concat — no libass / `subtitles=` filter, so it works with
Homebrew's stock ffmpeg.

### Job model

`JOBS` is an in-process dict keyed by a random 10-hex `job_id`. On disk we
also persist `jobs/{id}/plan.json` so `build_final` can be called from a
fresh process (e.g. from `cli.py --resume <id>`).

---

## User manual

The full step-by-step guide — install, backends, web UI, terminal UI,
one-shot end-to-end (Claude / Ollama / cloud), troubleshooting, cost —
lives in **[USER_MANUAL.md](USER_MANUAL.md)**.

Quick starts:

```bash
# Web UI
.venv/bin/uvicorn app:app --reload --port 8000   # → http://localhost:8000

# Interactive terminal
.venv/bin/python cli.py

# Hands-off one-shot (Claude Code subscription)
echo "your rough points ." | BACKEND=claude_cli .venv/bin/python cli.py --auto-narrate

# Hands-off one-shot (Ollama, free / local)
echo "your rough points ." | BACKEND=ollama OLLAMA_MODEL=llama3.2 .venv/bin/python cli.py --auto-narrate
```

See [USER_MANUAL.md](USER_MANUAL.md) for prerequisites, backend setup,
slide-edit and audio-upload flows, and troubleshooting.
