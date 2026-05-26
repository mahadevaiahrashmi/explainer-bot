# Testing & UAT Guide

How we keep Explainer Bot working. This document covers:

1. **Reporting visual problems** (the most common kind of issue) — what
   the in-app "ask bot to fix" feature handles and what should be filed
   as a GitHub issue.
2. **Code-testing strategy** — what's automated, what's not, and why.
3. **Smoke test** — the one script that exercises the whole pipeline.
4. **User Acceptance Testing checklist** — what to verify by eye before
   shipping a change.
5. **Bug-reporting workflow** — how to file an issue we can act on.

---

## 1. Reporting visual problems

> **Text overlaps, runs off the edge, labels unreadable, diagram in the
> wrong place** — these are slide-design problems, not bugs in the code.
> Fix them inside the bot, not on GitHub.

There are three layers of fix, in order of escalating effort. Try them
top to bottom.

### Layer A — "Ask bot to fix this slide" *(always try this first)*

This is the canonical workflow for any visual problem with a slide.

**Web UI** — in the *Slides* stage, pick the affected slide's tab, then:

1. Click **"Report issue / ask bot to fix"** (it's next to "Re-render
   this slide").
2. Describe the problem in plain English. Be specific about what's wrong
   and where. Examples that work well:
   - *"The title overlaps the diagram on the left side."*
   - *"The second equation runs off the right edge of the slide."*
   - *"The bottom label is dark grey on a dark blue background — I can't
     read it."*
   - *"The arrow between the two boxes is pointing the wrong way."*
   - *"There's too much empty space at the bottom. Make the diagram
     bigger."*
3. Click **"Ask bot to fix this slide."** Wait ~20–40 s; the iframe and
   the PNG link update with the new version.

**Terminal UI** — at the slide-edit prompt, type `f 2` (for slide 2),
then type the issue description, end with a single `.` on its own line.

**What's happening:** the bot reads the current HTML, the original
slide brief (title + key_visual + aesthetic), and your issue
description, then rewrites just that slide's HTML to address the
specific problem while preserving the rest. It then re-screenshots
that one slide.

**Tips for getting a good fix:**
- Be concrete about *what* and *where*. "Looks bad" gives the bot
  nothing to act on; "the title overlaps the diagram on the left"
  tells it exactly what to move.
- One issue per request. If two things are broken, fix them in two
  passes — easier to revert if the bot over-corrects.
- If the fix made it worse, click **"Revert to bot's version"** (which
  reverts to the *last saved* version, including the bad fix) — or
  just call the fix again with a clearer description.

### Layer B — Edit the HTML directly

If the bot's fix doesn't work after 2–3 tries, edit the HTML yourself:

- **Web UI** — the left panel is a live HTML editor. Change it, hit
  *Re-render this slide*. The right panel updates after the
  re-screenshot.
- **Terminal UI** — at the slide-edit prompt, type the slide number
  (e.g. `2`) to open `slide_NN.html` in `$EDITOR`. Save and quit, then
  type `d` to build the cue video (which re-screenshots all slides).

The slides are intentionally plain HTML + inline CSS, no frameworks,
no build step — you can hand-tune anything in a few minutes.

### Layer C — File a GitHub issue

File an issue **only if** Layers A and B didn't help and you think the
problem is a real bug in the bot (e.g. the bot's fix always fails the
same way, or every slide overflows on a particular aspect ratio).

See §5 below for what to include.

---

## 2. Code-testing strategy

We deliberately keep test infrastructure small. The project is a
single-user local tool with two main quality bars:

- **Pipeline works end-to-end** — rough points produce a valid MP4.
- **The bot's output is actually good** — script reads well, slides
  look right.

The first is best covered by **smoke tests**; the second is best
covered by **UAT** (a human looking at a video). Unit tests for the
in-between layers earn their keep only when there's deterministic
behaviour to assert against.

| Test kind                  | Scope                                                                                  | Where it lives                   | Cost                                  |
| -------------------------- | -------------------------------------------------------------------------------------- | -------------------------------- | ------------------------------------- |
| **Smoke test** (current)   | One end-to-end pipeline run with a fixed input. Uses `say` as stand-in for voice.       | `smoke_test.py`                   | ~3–5 min, ~3 Claude calls per run.     |
| **Unit / pytest** (future) | Pure-function helpers (`_estimate_duration`, `_extract_json`, `find_audio_for_slide`). | `tests/test_helpers.py` *(TBD)*  | Fast, no Claude. Add when you change those helpers. |
| **API contract tests** (future) | HTTP shape of every endpoint, with the pipeline mocked.                                 | `tests/test_api.py` *(TBD)*      | Fast. Use `pytest`+`httpx.AsyncClient` and monkeypatch `pipeline.*`. |
| **UAT** *(see §4)*         | A human watches the final video and ticks a checklist.                                  | This document.                    | ~5 minutes per release.                |

The smoke test is the only one that exists today; the others are
appropriate to add as the surface grows. There is intentionally no
testing of *Claude's output quality* — the `CRITIC_PROMPT` does that
inside the pipeline.

---

## 3. Smoke test

`smoke_test.py` drives both pipeline stages end-to-end without any
human in the loop. It uses macOS `say` to stand in for the user's
voice recordings so it can run unattended.

### Running it

```bash
cd /Users/rashmi/Documents/content
.venv/bin/python smoke_test.py
```

### What it does, step by step

1. Calls `pipeline.draft_script` with a fixed "What is recursion?"
   prompt and inspects: topic / aesthetic / critique verdict / segment
   count.
2. Truncates to 2 segments to keep the test fast.
3. Calls `pipeline.build_cue` (which internally runs
   `design_slides` → `screenshot_slides` → `assemble_cue_video`) and
   verifies `cue_video.mp4` and `script.txt` exist.
4. Uses `say -o slide_NN.aiff "..."` to fake user audio for each slide.
5. Calls `pipeline.audio_status` and asserts `all_present == True`.
6. Calls `pipeline.build_final` and prints the final MP4 path and size.

### What it covers

- Claude CLI is reachable and returns parseable JSON for writer /
  critic / aesthetic / slide-designer prompts.
- Playwright + Chromium are installed and can render HTML to PNG.
- ffmpeg / ffprobe build silent cue and voiced final videos.
- The plan.json handoff between stages works.
- The audio-status / find-audio-for-slide filename matching works.

### What it does NOT cover

- Visual correctness of slides (a human has to look).
- Audio quality (it uses `say`).
- The web UI or CLI (it goes straight through the pipeline).
- The "Fix slide" or "Auto-narrate" features (run those by hand).
- Error paths — only the happy path.

### Adding a new smoke test case

Copy `smoke_test.py`, change the `rough` input and the assertions,
save as `smoke_test_<topic>.py`. Don't try to parametrise — keeping
each test as a standalone runnable script is more useful than a
pytest suite for this tool.

---

## 4. User Acceptance Testing checklist

Run through this before merging any change that touches the pipeline,
prompts, or the slide-design HTML. It takes ~5 minutes if everything
works.

### Stage 1 — script generation

- [ ] `POST /script` returns within 60 s.
- [ ] All 4–8 segments have a `title`, `key_visual`, and `narration`.
- [ ] Narration is *spoken* prose (no bullet points, no headings).
- [ ] At least one segment contains a concrete analogy.
- [ ] Critique returns 3 scores (understandability, analogies, wonder)
      all on a 1–5 scale.
- [ ] Critique notes are actionable and short (not "good job" filler).
- [ ] Aesthetic returns a name, ≥3-colour palette, font_family, and
      description.

### Stage 2 — slide design

- [ ] `POST /design` returns within 60 s.
- [ ] Each slide HTML starts with `<!doctype html>` and contains the
      `width:1920px;height:1080px` body.
- [ ] No slide references remote assets (no `http://` or `https://`).
- [ ] Each slide has its title rendered visibly.
- [ ] Each slide has a visual element matching `key_visual` (not just a
      title on an empty background).

### Stage 3 — slide-edit loop (web UI)

- [ ] Tab bar shows all slides.
- [ ] Switching tabs swaps the HTML in the textarea, the iframe
      preview, and the PNG link.
- [ ] Typing in the textarea updates the iframe live.
- [ ] "Re-render this slide" updates the PNG without affecting other
      slides.
- [ ] "Revert to bot's version" restores the last saved HTML.
- [ ] "Report issue / ask bot to fix" produces new HTML *related to*
      the reported issue (not unrelated).
- [ ] Tab marker dot (●) appears when there are unsaved edits and
      disappears after save / revert.

### Stage 4 — cue video

- [ ] `cue_video.mp4` opens in QuickTime / VLC.
- [ ] Resolution is 1920×1080.
- [ ] All slides appear in order.
- [ ] Slide durations are ≥ 4 s and look proportional to narration
      length.
- [ ] `script.txt` opens, has one block per slide, has timestamps and
      filename hints, and the narration text matches what `/script`
      returned.

### Stage 5 — audio ingest

- [ ] Drag-drop a `.wav` named `slide_00.wav` and verify the table
      shows `have_audio: true` with a duration.
- [ ] Upload a file named badly (e.g. `Slide00.wav`) and verify the
      table still shows that slide as missing.
- [ ] Click "Remove" on a slide and verify it goes back to missing.
- [ ] Click "Auto-narrate missing slides" — only previously-missing
      slides should be populated; existing user uploads should be left
      alone.
- [ ] Click "Auto-narrate everything (overwrite)" with the confirm
      prompt — everything is replaced.

### Stage 6 — final video

- [ ] `video.mp4` opens, plays, has audio.
- [ ] Each slide's screen time matches its audio length within 0.5 s.
- [ ] No "blip" or audio gap at slide boundaries.
- [ ] No subtitles / on-screen text on slides (that's the cue video's
      job — sorry, neither has subtitles in this version).

### Cross-cutting

- [ ] CLI flow `python cli.py` works end-to-end with the same job.
- [ ] CLI flow `python cli.py --auto-narrate` produces a final video
      with no manual recording step.
- [ ] CLI flow `python cli.py --resume <job_id>` jumps straight to the
      audio stage of an existing job.
- [ ] Restarting the server mid-build does not corrupt anything on
      disk for that job; re-running the relevant stage recovers.

---

## 5. Bug-reporting workflow

### Before you file

1. Have you tried "Ask bot to fix this slide" two or three times? Most
   visual issues are best solved in the bot, not on GitHub. See §1.
2. Is the issue reproducible? "It looked weird once" is not a bug. Run
   it twice and check.
3. If it's a slide that looks wrong, capture the *bad* version: copy
   the contents of `jobs/<job_id>/slides/slide_NN.html` and the PNG.

### What a good bug report contains

- **What you typed** (rough points), or what input triggered the bug.
- **What you expected** to happen.
- **What actually happened** (error message, screenshot, MP4
  attachment, copy of the bad HTML).
- **Stage** the problem occurred at (script / design / slide-edit /
  cue / audio / final).
- **Web UI or CLI**, and the exact command if CLI.
- **Output of**:
  ```bash
  cd /Users/rashmi/Documents/content
  echo "BACKEND=${BACKEND:-(auto)}  LLM_MODEL=${LLM_MODEL:-(unset)}  OLLAMA_MODEL=${OLLAMA_MODEL:-(unset)}"
  .venv/bin/python -c "import pipeline; print('resolved backend =', pipeline.get_backend())"
  claude --version 2>/dev/null   || echo "claude CLI: not installed"
  .venv/bin/llm --version 2>/dev/null || echo "llm CLI: not installed"
  ollama --version 2>/dev/null   || echo "ollama: not installed"
  ffmpeg -version | head -1
  .venv/bin/python -c "import playwright, fastapi, sys; print(sys.version)"
  ```
- For pipeline failures: the `progress` list from
  `GET /jobs/{id}/status` (the chat UI shows it; in the CLI it scrolls
  by). Or zip up `jobs/<job_id>/` if it's not too large — that has the
  plan, slide HTML, and everything else needed to reproduce.

### Categories

| Label                | What it means                                                                                                              |
| -------------------- | -------------------------------------------------------------------------------------------------------------------------- |
| `bug`                | Pipeline broke; an endpoint 500'd; a stage failed; the final MP4 is corrupt.                                               |
| `visual`             | A slide looks wrong in a *repeatable* way — i.e., the bot's fix step doesn't help. Include the bad HTML.                  |
| `quality`            | Script reads badly even after a few drafts. Include the rough points and the bad output. (Often a prompts.py issue.)        |
| `feature`            | Something new you want.                                                                                                    |
| `docs`               | README / SYSTEM_DESIGN / this file is wrong, missing, or misleading.                                                       |

Templates for the first three are in
[`.github/ISSUE_TEMPLATE/`](.github/ISSUE_TEMPLATE/). Open the issue
from GitHub's web UI and the template will guide you.

### Where to file

<https://github.com/mahadevaiahrashmi/explainer-bot/issues>
