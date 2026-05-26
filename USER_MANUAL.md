# Explainer Bot — User Manual

Step-by-step guide for installing, running, and using the explainer bot.
The bot turns a few rough points into a narrated explainer video.

> **Other docs:**
> [README](./README.md) (intro & tech stack) ·
> [PRD](./PRD.md) (product requirements) ·
> [PRODUCT_DESIGN](./PRODUCT_DESIGN.md) (UX) ·
> [SYSTEM_DESIGN](./SYSTEM_DESIGN.md) (architecture) ·
> [TESTING](./TESTING.md) (test + UAT) ·
> [docs/reviewer.md](./docs/reviewer.md) (how the critic works)

---

## Contents

- [One-time setup](#one-time-setup)
- [Backend configuration](#backend-configuration) — Claude Code / Ollama / cloud key
- [Web UI](#web-ui)
- [Terminal UI](#terminal-ui)
- [One-shot end-to-end](#one-shot-end-to-end-no-clicks-no-recording)
- [Files you get per job](#files-you-get-per-job)
- [Re-recording a single slide](#re-recording-a-single-slide)
- [Smoke test](#smoke-test)
- [Troubleshooting](#troubleshooting)
- [Cost / quota](#cost--quota)

---

## One-time setup

You need macOS, Homebrew, and **one** of the three LLM backends (see
[Backend configuration](#backend-configuration) for details — Claude Code,
Ollama, or any cloud key via `llm`).

```bash
brew install ffmpeg
cd content
uv venv --python 3.11
uv sync
.venv/bin/playwright install chromium
```

Verify the chosen backend is wired up:

```bash
.venv/bin/python -c "import pipeline, asyncio; print('backend =', pipeline.get_backend()); \
    asyncio.run(pipeline.llm_call('Reply with exactly OK.', 'go')) and print('reply ok')"
```

## Backend configuration

`BACKEND=` (env var) picks which one to use. Unset = auto-detect, preferring
`claude_cli` → `ollama` → `llm` in that order.

### Backend 1 — `claude_cli` (Claude Code subscription, no API key)

Already installed Claude Code? You're done. The bot detects the `claude`
binary and uses your subscription. Verify with `claude --version`.

```bash
export BACKEND=claude_cli   # optional; auto-detected anyway
```

### Backend 2 — `ollama` (free, local, no internet)

```bash
brew install ollama
brew services start ollama  # starts the daemon + auto-starts on login
ollama pull llama3.2        # ~2 GB; or qwen2.5:14b (~9 GB) for better quality
export BACKEND=ollama
export OLLAMA_MODEL=llama3.2          # default
# export OLLAMA_URL=http://localhost:11434    # default
```

Slide design and the critic prompt benefit a lot from a bigger model;
`qwen2.5:14b` or `llama3.3:70b` are noticeably better than `llama3.2`.
Trade-off: a single slide-design call on a laptop CPU is 30–90 s with a
14 B model.

#### Web UI on Ollama by default

```bash
BACKEND=ollama .venv/bin/uvicorn app:app --port 8000
```

Open <http://127.0.0.1:8000>. The picker badge will read
`ollama:llama3.2 (env)`.

**Per-request switching in the web UI:** leave `BACKEND` unset when
starting the server, then in the model picker at the top of the page
pick `ollama — local, free` and put `llama3.2` (or any other model
you've pulled) in the model box. Each request picks that backend.

#### Two caveats with `llama3.2`

1. **Speed.** On Apple Silicon CPU, a single slide-design call takes
   ~30–60 s; a 6-slide video will spend 3–6 minutes in Ollama work
   alone. (Subscription Claude is closer to 5–10 s per call.)
2. **Quality drop on slide HTML.** `llama3.2` is fine for the script
   and critic, but its slide HTML is less restrained than Claude's —
   you'll hit the "ask bot to fix this slide" loop more often. If you
   have RAM to spare, `ollama pull qwen2.5:14b` (~9 GB) is a
   meaningful upgrade for slide design:

   ```bash
   ollama pull qwen2.5:14b
   BACKEND=ollama OLLAMA_MODEL=qwen2.5:14b .venv/bin/python cli.py --auto-narrate
   ```

#### Useful Ollama commands

```bash
ollama list                     # what models you have
ollama ps                       # what's loaded in RAM right now
ollama pull <model>             # add a model
ollama rm <model>               # remove a model
brew services stop ollama       # stop the daemon
brew services start ollama      # start it again (or after reboot, it's already on)
```

### Backend 3 — `llm` (cloud API key — Anthropic / OpenAI / Gemini / …)

The `llm` CLI is already in our dependencies. Pick a provider and set its
key:

```bash
# Pick one:
.venv/bin/llm keys set claude        # Anthropic API key  (paste when prompted)
.venv/bin/llm keys set openai        # OpenAI API key
.venv/bin/llm keys set gemini        # Gemini API key (free tier)

# Pick the model — anything llm knows about:
export BACKEND=llm
export LLM_MODEL=claude-sonnet-4-5           # Anthropic
# export LLM_MODEL=gpt-4.1                   # OpenAI
# export LLM_MODEL=gemini-2.0-flash          # Gemini (has a free tier)
```

`.venv/bin/llm models` lists every model your installed plugins know
about. Cost depends on the provider's pricing per token. Quality:
Claude-Sonnet ≥ GPT-4.1 ≈ Gemini-2.0 for this task.

---

## Web UI

```bash
cd content
.venv/bin/uvicorn app:app --reload --port 8000
```

Open <http://localhost:8000> and:

1. **Type rough points** into the panel at the top → "Draft script."
   (The rough-points panel stays visible on every stage — edit it and
   click "Draft script" again at any point to redraft.)
2. **Review the script + critique.** Edit any title / visual / narration
   in place. Click **"Approve script → design slides."**
3. **Slide HTML appears.** A tab bar at the top lists every slide. Pick
   a tab; on the left you see the raw HTML in an editable textarea, on
   the right a live iframe preview that updates as you type. Click
   **"Re-render this slide"** to save the edit and refresh the PNG;
   **"Revert to bot's version"** to throw away unsaved edits. If the
   slide has a problem you can describe in words (overlapping text, the
   diagram in the wrong place, an unreadable label), click **"Report
   issue / ask bot to fix"**, describe the issue, and the bot will
   rewrite that slide's HTML — no need to edit by hand. Click
   **"Build cue video"** when all slides look right.
4. **Cue video appears.** Watch it, download it, download `script.txt`.
5. **Record one audio file per slide** (`slide_00.wav`, `slide_01.wav`,
   …) — any common audio format (.wav, .mp3, .m4a, .aiff, …).
6. **Drag-drop the files** onto the upload area. The status table shows
   which slides have audio. You can remove and re-upload one slide at a
   time.
7. When all slides are green, click **"Build final video."** A few
   seconds later the MP4 is playable and downloadable in-page.

If you want to skip recording entirely (or just preview the video
before committing to a take), click **"Auto-narrate missing slides"** —
macOS `say` will fill in any slide you don't have a recording for. Use
**"Auto-narrate everything (overwrite)"** to replace all slides at
once.

### Switching models per request

A picker strip at the top of every page lets you change backend / model
on a per-request basis. The badge shows the current server default; the
picker overrides it. The picker rides along on `/script`, `/design`,
and `/slide/{i}/fix`.

---

## Terminal UI

```bash
cd content
.venv/bin/python cli.py
```

Same flow as the web UI, but:

- Multi-line input ends with a single `.` on its own line.
- Approve / edit / redraft is keyboard-driven.
- "Edit in editor" opens the script in `$EDITOR` as a Markdown file
  with one section per slide.
- After approving the script the bot writes one `slide_NN.html` per
  slide and lists them with their paths. Type a slide number to edit
  that HTML in `$EDITOR`, `o` to open the slides folder in Finder, or
  `d` to proceed to building the cue video.
- After the cue is built, the bot prints the audio folder path and
  waits. Record your files, save them into that folder, hit `r` to
  rescan. When all are present, hit `f` to finalize.
- Resume an existing job: `.venv/bin/python cli.py --resume <job_id>`
  jumps straight to the audio stage.
- Skip recording entirely: `.venv/bin/python cli.py --auto-narrate`
  runs end-to-end with macOS `say` filling in every slide. Combine
  with `--resume` to auto-narrate an existing job in one command.
- At the audio prompt, `n` synthesises any missing slides with `say`;
  `a` replaces every slide's audio with synthesis (asks first).

---

## One-shot end-to-end (no clicks, no recording)

Pipe rough points into the CLI with `--auto-narrate` and you get a
finished MP4 in one command. `--auto-narrate` auto-approves the script,
skips the slide-edit menu, narrates with macOS `say`, and assembles
the final video — completely hands-off. Pick the backend with the
`BACKEND` env var.

### With a Claude Code subscription (best quality, no API key, no cost)

```bash
cd /Users/rashmi/Documents/content
echo "What is recursion?
- a function that calls itself
- needs a base case
- the matryoshka / Russian-doll analogy
- a brief example: factorial
." | BACKEND=claude_cli .venv/bin/python cli.py --auto-narrate
```

Wall-clock: ~3–5 minutes for a 6-slide video.
Output: `jobs/<id>/video.mp4` (opens automatically when done).

### Fully free, local, no internet (Ollama)

```bash
cd /Users/rashmi/Documents/content
echo "What is recursion?
- a function that calls itself
- needs a base case
- the matryoshka / Russian-doll analogy
- a brief example: factorial
." | BACKEND=ollama OLLAMA_MODEL=llama3.2 .venv/bin/python cli.py --auto-narrate
```

Wall-clock: ~8–15 minutes on Apple Silicon CPU (Ollama is slower than
Claude's hosted inference, especially on the slide-design calls). Costs
nothing.

For better slide quality, pull and use a bigger model:

```bash
ollama pull qwen2.5:14b
echo "your rough points here ." | \
  BACKEND=ollama OLLAMA_MODEL=qwen2.5:14b .venv/bin/python cli.py --auto-narrate
```

> **Note:** smaller Ollama models sometimes return malformed JSON for
> the writer or critic step. The pipeline tries to recover quietly, but
> if it can't, you'll see a clear error suggesting you switch to a
> bigger model (e.g. `qwen2.5:14b`) or a different backend.

### With any cloud key (Anthropic / OpenAI / Gemini …)

```bash
.venv/bin/llm keys set claude        # one-time, paste your Anthropic key
echo "your rough points here ." | \
  BACKEND=llm LLM_MODEL=claude-sonnet-4-5 .venv/bin/python cli.py --auto-narrate
```

Substitute `LLM_MODEL=gpt-4.1` (OpenAI), `gemini-2.0-flash` (Gemini's
generous free tier), or any model `.venv/bin/llm models` lists.

### What it does, in all three cases

1. drafts a script + critique (1 reviewer pass)
2. designs HTML for each slide
3. screenshots slides via Playwright
4. synthesises narration with macOS `say`
5. assembles the final MP4

No prompts, no clicks. The final video opens in QuickTime automatically.

---

## Files you get per job

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

## Re-recording a single slide

Just replace the file in `jobs/<job_id>/audio/` (delete the old one if
the extension changes) and run finalize again — in the web UI, the
table has a "Remove" button per slide; in the CLI, drop in a new file
and hit `f`.

## Smoke test

Stand-in test that runs end-to-end without you having to actually
record:

```bash
cd content
.venv/bin/python smoke_test.py
```

It uses `say` as a placeholder voice so the test runs unattended. A
real session would skip step `[3/4]` and use your own recordings
instead.

## Troubleshooting

- **"No LLM backend available"** — install one of: Claude Code (`claude`
  CLI), Ollama (`brew install ollama && ollama serve && ollama pull
  llama3.2`), or run `llm keys set <provider>` for the `llm` backend.
  See [Backend configuration](#backend-configuration).
- **"claude CLI timed out"** — `claude -p "hi"` probably hangs at the
  auth prompt. Run `claude` once interactively to log in, then retry.
- **"Ollama at … unreachable"** — `brew services start ollama` (or run
  `ollama serve` in another terminal), then `ollama pull <model>` if
  the named model isn't downloaded.
- **"`llm` CLI failed: No key found"** — run `.venv/bin/llm keys set
  <provider>` (e.g. `claude`, `openai`, `gemini`) and set
  `LLM_MODEL=` to a model that provider supports.
- **"Expected JSON object … got a list of N items"** — your model
  isn't following the JSON schema. Common with very small Ollama
  models. Try a bigger Ollama model (`qwen2.5:14b`) or switch
  `BACKEND=`.
- **Slide content too low / runs off the screen** — regenerate the
  slide, or describe the issue ("title overlaps diagram") via the web
  UI's "Ask bot to fix" panel. The slide-designer prompt has explicit
  no-overlap rules, but small models don't always follow them.
- **"missing audio file for slide N"** — filenames must start with
  `slide_NN` (zero-padded). The audio dir is shown in both UIs.
- **Final video plays but slides are too long / short** — that's just
  the audio length. Re-record that slide more tightly and re-finalize.

## Cost / quota

Each video uses roughly:

- 1 writer call (~2 k output tokens)
- 1 aesthetic-picker call (~200 tokens)
- 1 critic call (~500 tokens)
- N slide-design calls (~1 k tokens each), one per segment

Where those calls hit, and what they cost, depends on the backend:

- **`claude_cli`** — counts against your Claude Code subscription
  allowance, no extra billing.
- **`ollama`** — runs locally, no charge, no internet.
- **`llm`** — billed by the upstream provider (Anthropic / OpenAI /
  Gemini / …) at their token pricing. ~$0.02–$0.05 per video on
  Claude Sonnet at current prices; Gemini's free tier covers casual
  use.
