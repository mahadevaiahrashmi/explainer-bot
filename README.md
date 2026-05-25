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
All Claude calls go through your **Claude Code subscription** — no
`ANTHROPIC_API_KEY` needed.

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
| LLM                  | **Claude** via the local **`claude` CLI** | Routes every model call through the user's Claude Code subscription — no API key, no per-call cost. Swappable: replace `pipeline.claude()` to switch backends. |
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

Nothing per video, beyond the Claude Code subscription you already have.
The bot uses the `claude` CLI under the hood, so the script-writing,
critique, and slide-design calls count against your normal subscription
allowance, not a paid API account.

---

## For technical readers

> - Full architectural reference (components, API contracts, sequence
>   diagrams, decision log) → **[SYSTEM_DESIGN.md](SYSTEM_DESIGN.md)**.
> - Testing strategy, UAT checklist, and bug-reporting workflow →
>   **[TESTING.md](TESTING.md)**.
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

### One-time setup

You need macOS, Homebrew, and Claude Code installed and logged in.

```bash
brew install ffmpeg
cd content
uv venv --python 3.11
uv sync
.venv/bin/playwright install chromium
```

Verify the `claude` CLI is reachable:

```bash
claude -p "say hello"
```

### Web UI

```bash
cd content
.venv/bin/uvicorn app:app --reload --port 8000
```

Open <http://localhost:8000> and:

1. **Type rough points** → "Draft script."
2. **Review the script + critique.** Edit any title / visual / narration in
   place. Click **"Approve script → design slides."**
3. **Slide HTML appears.** A tab bar at the top lists every slide. Pick a
   tab; on the left you see the raw HTML in an editable textarea, on the
   right a live iframe preview that updates as you type. Click
   **"Re-render this slide"** to save the edit and refresh the PNG;
   **"Revert to bot's version"** to throw away unsaved edits. If the
   slide has a problem you can describe in words (overlapping text, the
   diagram in the wrong place, an unreadable label), click **"Report
   issue / ask bot to fix"**, describe the issue, and the bot will
   rewrite that slide's HTML — no need to edit by hand. Click
   **"Build cue video"** when all slides look right.
4. **Cue video appears.** Watch it, download it, download `script.txt`.
5. **Record one audio file per slide** (`slide_00.wav`, `slide_01.wav`, …) —
   any common audio format (.wav, .mp3, .m4a, .aiff, …).
6. **Drag-drop the files** onto the upload area. The status table shows
   which slides have audio. You can remove and re-upload one slide at a time.
7. When all slides are green, click **"Build final video."** A few seconds
   later the MP4 is playable and downloadable in-page.

If you want to skip recording entirely (or just preview the video before
committing to a take), click **"Auto-narrate missing slides"** — macOS
`say` will fill in any slide you don't have a recording for. Use
**"Auto-narrate everything (overwrite)"** to replace all slides at once.

### Terminal UI

```bash
cd content
.venv/bin/python cli.py
```

Same flow, but:
- Multi-line input ends with a single `.` on its own line.
- Approve / edit / redraft is keyboard-driven.
- "Edit in editor" opens the script in `$EDITOR` as a Markdown file with
  one section per slide.
- After approving the script the bot writes one `slide_NN.html` per
  slide and lists them with their paths. Type a slide number to edit
  that HTML in `$EDITOR`, `o` to open the slides folder in Finder, or
  `d` to proceed to building the cue video.
- After the cue is built, the bot prints the audio folder path and waits.
  Record your files, save them into that folder, hit `r` to rescan.
  When all are present, hit `f` to finalize.
- Resume an existing job: `.venv/bin/python cli.py --resume <job_id>`
  jumps straight to the audio stage.
- Skip recording entirely: `.venv/bin/python cli.py --auto-narrate` runs
  end-to-end with macOS `say` filling in every slide. Combine with
  `--resume` to auto-narrate an existing job in one command.
- At the audio prompt, `n` synthesises any missing slides with `say`; `a`
  replaces every slide's audio with synthesis (asks first).

### Files you get per job

After `build_cue` runs you have:

```
jobs/<job_id>/
├── plan.json              # the approved script (used by build_final)
├── slides/                # slide HTML + PNG screenshots
├── audio/                 # drop your slide_NN.wav files here
├── work/                  # ffmpeg intermediate files
├── cue_video.mp4          # silent slideshow, estimated durations
└── script.txt             # per-slide narration + timestamps + filename to record
```

After `build_final` runs you also get `jobs/<job_id>/video.mp4`.

### Re-recording a single slide

Just replace the file in `jobs/<job_id>/audio/` (delete the old one if the
extension changes) and run finalize again — in the web UI, the table has a
"Remove" button per slide; in the CLI, drop in a new file and hit `f`.

### Smoke test

Stand-in test that runs end-to-end without you having to actually record:

```bash
cd content
.venv/bin/python smoke_test.py
```

It uses `say` as a placeholder voice so the test runs unattended. A real
session would skip step `[3/4]` and use your own recordings instead.

### Troubleshooting

- **"claude CLI timed out"** — `claude -p "hi"` probably hangs at the auth
  prompt. Run `claude` once interactively to log in, then retry.
- **Slide content too low / runs off the screen** — regenerate the slide,
  or edit `key_visual` to be more specific ("centered in the frame", "three
  labeled circles in a row") and re-approve.
- **"missing audio file for slide N"** — filenames must start with
  `slide_NN` (zero-padded). The audio dir is shown in both UIs.
- **Final video plays but slides are too long / short** — that's just the
  audio length. Re-record that slide more tightly and re-finalize.

### Cost / quota

Each video uses roughly:
- 1 writer call (~2 k output tokens)
- 1 aesthetic-picker call (~200 tokens)
- 1 critic call (~500 tokens)
- N slide-design calls (~1 k tokens each), one per segment

All routed through your Claude Code subscription. No API key is charged.
