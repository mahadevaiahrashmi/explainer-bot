# Explainer Bot — System Design

This document is the authoritative architectural reference for the
Explainer Bot. It describes what the system does, how it's composed, the
contracts each component exposes, the request/response shapes of the HTTP
API, the sequence of events for each user flow, the persistence model, the
failure modes we tolerate, and the rationale behind the key design
choices. The user-facing README is the entry point for *running* the tool;
this document is the entry point for *changing* it.

---

## 1. Goals and non-goals

### Goals
- Turn a few rough points into a finished, narrated, 1920×1080 explainer
  video without anyone writing code.
- Keep the voice on the final video human. The reviewer's quality bar is
  the [3Blue1Brown video on neural networks](https://www.youtube.com/watch?v=jx6FevmKJGg):
  vivid analogies, undergrad-readable, with a genuine sense of wonder.
- Use the user's existing **Claude Code subscription** as the only LLM
  credential. No `ANTHROPIC_API_KEY`, no per-call billing.
- Run entirely on a single laptop with no cloud dependencies and no
  long-lived process state — closing the terminal must not lose work.
- Offer **both** a web UI (for newcomers) and a terminal UI (for power
  users), backed by the same pipeline so they never diverge.

### Non-goals (today)
- No multi-user / authentication. The HTTP server is bound to
  `127.0.0.1` and stores everything under `jobs/` in the project dir.
- No GPU rendering. All slides are static HTML screenshots — there is no
  Manim-style animation engine in scope.
- No cloud storage, no queue. Jobs are in-process tasks; killing the
  server cancels in-flight work (the user can re-run `build_cue` /
  `build_final` to recover, because each stage is idempotent on disk).
- No automatic upload to YouTube or anywhere else.

---

## 2. Architecture at a glance

```
                  ┌──────────────────────┐
                  │      USER INPUT      │
                  │ "rough points" text  │
                  └─────────┬────────────┘
                            │
                            ▼
                  ┌──────────────────────┐
                  │     SCRIPT STAGE     │
                  │  draft_script(…)     │
                  │  3 parallel claude   │
                  │  calls + parse JSON  │
                  └─────────┬────────────┘
                            │  ScriptDraft (in-memory)
                            ▼
                  ┌──────────────────────┐
                  │   USER REVIEW LOOP   │
                  │ edit / approve /     │
                  │ redraft segments     │
                  └─────────┬────────────┘
                            │  approved segments
                            ▼
                  ┌──────────────────────┐
                  │      CUE STAGE       │   per-job dir on disk:
                  │   build_cue(…)       │     plan.json
                  │                      │     slides/slide_NN.html|png
                  │  • N claude calls    │     audio/    (empty)
                  │    (slide HTML)      │     work/
                  │  • N playwright PNG  │     cue_video.mp4
                  │  • silent ffmpeg     │     script.txt
                  │    cue_video + txt   │
                  └─────────┬────────────┘
                            │  audio_dir path
                            ▼
              ┌─────────────────────────────────┐
              │     AUDIO INGEST (any mix)      │
              │  ┌────────────┐ ┌────────────┐  │
              │  │ user drops │ │   button   │  │
              │  │  slide_NN  │ │ "auto-     │  │
              │  │   files    │ │ narrate"   │  │
              │  └─────┬──────┘ └─────┬──────┘  │
              │        │     ↑↓       │         │
              │        │  any combo   │         │
              │        ▼              ▼         │
              │  jobs/<id>/audio/ has one file  │
              │  per slide  (slide_NN.<ext>)    │
              └─────────────┬───────────────────┘
                            │
                            ▼
                  ┌──────────────────────┐
                  │     FINAL STAGE      │
                  │  build_final(…)      │   adds to per-job dir:
                  │                      │     work/final_clip_NN.mp4
                  │  • ffprobe duration  │     video.mp4
                  │  • ffmpeg clip × N   │
                  │  • concat → video    │
                  └─────────┬────────────┘
                            │
                            ▼
                          MP4
```

Two stages, two artifacts (cue video + final video). All state between
stages lives on disk under `jobs/<job_id>/`, so any stage can be re-run
independently. The HTTP server and the CLI are thin wrappers around the
same `pipeline.*` functions.

---

## 3. Components

The codebase is intentionally small — 5 source files. Each one has a
narrow responsibility.

| File                  | Role                                                            | Stable interface                                                                                                                  |
| --------------------- | --------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------- |
| `pipeline.py`         | Pure-Python pipeline. The only module that knows about Claude, Playwright, `say`, and ffmpeg. | `draft_script(rough_points) → ScriptDraft` <br> `build_cue(topic, aesthetic, segments, job_id?, progress_cb?) → CueResult` <br> `auto_narrate(job_id, overwrite=False, progress_cb?) → list[Path]` <br> `audio_status(job_id) → dict` <br> `find_audio_for_slide(audio_dir, index) → Path \| None` <br> `build_final(job_id, progress_cb?) → FinalResult` |
| `prompts.py`          | All Claude system prompts. Pure data; no logic.                 | Module constants: `WRITER_PROMPT`, `CRITIC_PROMPT`, `SLIDE_DESIGNER_PROMPT`, `AESTHETIC_PICKER_PROMPT`.                           |
| `app.py`              | FastAPI HTTP server. Routes call into `pipeline.*` and persist state in process memory. | See §5 (API contracts).                                                                                                           |
| `cli.py`              | Interactive terminal UI. Same pipeline as the web UI, no HTTP.  | Entry point: `python cli.py [--resume JOB_ID] [--auto-narrate]`.                                                                  |
| `templates/chat.html` | Single-page chat UI. Vanilla JS, no build step. Polls the API.  | Talks only to the endpoints in §5.                                                                                                |

### 3.1 `pipeline.py` invariants

- All Claude calls go through one wrapper: `pipeline.claude(system_prompt,
  user_message) → str`. This is the **only** integration point with the
  LLM. To swap the `claude` CLI for the Anthropic SDK or a different
  backend, change this function alone.
- All ffmpeg invocations go through `_build_silent_clip` /
  `_build_voiced_clip` / `_concat_clips`. The shape of those calls
  (constant flags, no global state) is the reason we don't need
  ffmpeg-python.
- All slide-image rendering goes through `_screenshot_slide(html,
  out_png, browser)`. Playwright is the only browser dependency.
- `pipeline.py` never touches the network outside of the `claude`
  subprocess. Slide HTML must not reference remote assets (enforced by
  the slide-designer prompt and by Playwright running with no
  proxy/cache config).
- No global mutable state. Job IDs are random; state lives on disk under
  `JOBS_DIR / job_id`.

### 3.2 `app.py` invariants

- `JOBS: dict[str, dict[str, Any]]` is in-process state for *job
  progress* (status, progress messages, error). It is **not** the source
  of truth for the artifacts — `jobs/<id>/` on disk is. If the server
  restarts, in-flight progress is lost but completed cue/final videos
  are still on disk and can be served by re-creating a `JOBS[job_id]`
  entry pointing at them (the CLI's `--resume` does the equivalent).
- Every endpoint that performs I/O wraps the call in `try/except` and
  surfaces failures via either HTTP 5xx or `JOBS[job_id]["error"]`.
- Background jobs are `asyncio.create_task(...)`. They are *not*
  awaited at request time — the request returns the job id, the client
  polls `/jobs/{id}/status`.

### 3.3 `cli.py` invariants

- Uses the same `pipeline.*` API the FastAPI server uses. No duplicate
  business logic.
- Multi-line input ends with a single `.` on its own line, matching the
  classic `mail(1)` convention.
- Resuming with `--resume <job_id>` requires only `jobs/<id>/plan.json`
  to exist; the cue video and script.txt are not strictly needed (they
  can be regenerated by re-running cue if absent).

---

## 4. Data model

### 4.1 Dataclasses (pipeline.py)

```python
@dataclass
class Segment:
    title: str          # short, slide-headline
    key_visual: str     # one-sentence description; consumed by slide designer
    narration: str      # what the human (or `say`) reads aloud

@dataclass
class Aesthetic:
    name: str           # e.g. "Chalkboard Recursion"
    palette: list[str]  # CSS colour strings; first entry is the background
    font_family: str    # CSS font-family value
    description: str    # free-text design rationale

@dataclass
class Critique:
    scores: dict[str, int]   # always 3 keys: understandability, analogies, wonder (0..5)
    verdict: str             # "approve" | "revise"
    notes: list[str]         # short suggestions for the writer

@dataclass
class ScriptDraft:
    topic: str               # derived from the first non-empty line of rough_points
    segments: list[Segment]
    critique: Critique
    aesthetic: Aesthetic

@dataclass
class CueResult:
    job_id: str
    cue_video_path: Path
    script_text_path: Path
    slide_pngs: list[Path]
    estimated_durations: list[float]
    audio_dir: Path
    progress: list[str]

@dataclass
class FinalResult:
    job_id: str
    final_video_path: Path
    progress: list[str]
```

### 4.2 On-disk layout

```
jobs/
  <job_id>/                       random 10-hex lowercase
    plan.json                     {topic, aesthetic, segments}  — the contract
                                  with build_final. Written once by build_cue.
    slides/
      slide_00.html               raw HTML from claude (after fence-stripping)
      slide_00.png                playwright screenshot, 1920×1080
      slide_01.html
      slide_01.png
      ...
    audio/                        empty after cue, populated by user uploads
      slide_00.wav                or .mp3, .m4a, .aiff, .aac, .flac, .ogg, .opus
      slide_01.aiff               can come from `say` (auto-narrate) or upload
      ...
    work/                         ffmpeg intermediates; safe to delete
      cue_clip_00.mp4 ... cue_clip_NN.mp4
      final_clip_00.mp4 ... final_clip_NN.mp4
      concat.txt
    cue_video.mp4                 silent slideshow at estimated durations
    script.txt                    human-readable cue sheet
    video.mp4                     final narrated video (only after build_final)
```

`plan.json` is the source of truth for the script. `build_final` re-reads
it; the in-process `JOBS` dict is not consulted, which is what lets the
CLI's `--resume` work across server restarts.

### 4.3 Audio file naming

The pipeline matches files by filename stem only. Valid:

```
slide_00.wav   slide_01.mp3   slide_02.m4a   slide_03.aiff
slide_04.aac   slide_05.flac  slide_06.ogg   slide_07.opus
```

Anything else (e.g. `Slide00.wav`, `slide-0.wav`, `audio_00.wav`) is
ignored. `find_audio_for_slide` enforces this; `audio_status` reports the
first match per index in sorted order.

---

## 5. API contracts (FastAPI)

All endpoints accept and return `application/json` unless noted
otherwise. Errors are standard `{detail: str}` from FastAPI with the
appropriate 4xx/5xx status code.

### 5.1 `POST /script`

Generate a script + critique + aesthetic from rough points. **Synchronous**
— this is the user's first interactive turn and we want the response in
one shot, not a poll loop.

```jsonc
// Request
{ "rough_points": "What is recursion?\n- function calls itself\n- base case…" }

// Response 200
{
  "topic": "What is recursion?",
  "aesthetic": { "name": "...", "palette": ["#0e1216", ...],
                 "font_family": "Inter, ...", "description": "..." },
  "segments": [
    { "title": "...", "key_visual": "...", "narration": "..." },
    ...
  ],
  "critique": {
    "scores": { "understandability": 5, "analogies": 4, "wonder": 5 },
    "verdict": "approve",
    "notes": ["Consider clarifying the base case..."]
  }
}
```

Timeouts: each underlying `claude` call has a 240 s ceiling (see
`pipeline.CLAUDE_TIMEOUT_S`). Three calls total run partly in parallel so
worst case ≈ 4 min.

### 5.2 `POST /cue`

Kicks off the cue stage **asynchronously** in a background task. Returns
immediately with the job id; client polls `/jobs/{id}/status`.

```jsonc
// Request
{
  "topic": "What is recursion?",
  "aesthetic": { "name": "...", "palette": [...], "font_family": "...", "description": "..." },
  "segments": [{ "title": "...", "key_visual": "...", "narration": "..." }, ...]
}

// Response 200
{ "job_id": "aae6a72695" }
```

The client is expected to have already approved/edited the script in §5.1
before calling this. The server treats the request body as authoritative
— there is no server-side draft persistence between `/script` and `/cue`.

### 5.3 `GET /jobs/{job_id}/status`

The poll endpoint. Returns the current stage, status, progress log lines,
last error (if any), and whether artifacts exist.

```jsonc
// Response 200
{
  "stage": "cue" | "final",
  "status": "queued" | "running" | "done" | "error",
  "progress": ["Designing 6 slides in parallel...", "Captured slide 1/6", ...],
  "error": null | "exception message",
  "has_cue_video": true,
  "has_final_video": false,
  "audio": {                       // null until plan.json exists
    "job_id": "aae6a72695",
    "audio_dir": "/.../jobs/aae6a72695/audio",
    "slides": [
      { "index": 0, "title": "...", "expected_filename_stem": "slide_00",
        "have_audio": true,  "audio_filename": "slide_00.wav", "audio_duration_s": 15.4 },
      { "index": 1, ..., "have_audio": false, "audio_filename": null, "audio_duration_s": null }
    ],
    "all_present": false
  }
}
```

### 5.4 `GET /jobs/{job_id}/cue`

Streams `cue_video.mp4` (`video/mp4`). `Content-Disposition` set to
`attachment` with filename `<job_id>-cue.mp4`.

### 5.5 `GET /jobs/{job_id}/script`

Returns `script.txt` (`text/plain`).

### 5.6 `POST /jobs/{job_id}/audio`

Multipart form upload. Field name is `files` (repeatable). Saves each file
to `jobs/<id>/audio/<basename>`. `..` and absolute paths are defeated by
calling `Path(filename).name` before joining.

```jsonc
// Response 200
{ "saved": ["slide_00.wav", "slide_02.m4a"], "audio": { ...same as §5.3.audio... } }
```

### 5.7 `DELETE /jobs/{job_id}/audio/{index}`

Removes the audio file for the given slide index (0-based).

### 5.8 `POST /jobs/{job_id}/auto-narrate?overwrite=bool`

Synchronous-but-off-thread (`asyncio.to_thread`). Calls
`pipeline.auto_narrate(job_id, overwrite)`. Returns once `say` has
written every requested file.

```jsonc
// Response 200
{ "written": ["slide_00.aiff", "slide_02.aiff"], "audio": { ... } }
```

### 5.9 `POST /jobs/{job_id}/finalize`

Kicks off the final stage **asynchronously**. Same poll pattern as `/cue`.

```jsonc
// Response 200
{ "job_id": "aae6a72695" }
```

### 5.10 `GET /jobs/{job_id}/video`

Streams `video.mp4`. Same headers as `/cue`.

---

## 6. Sequence diagrams

### 6.1 Script generation

```
User           Chat UI        FastAPI         pipeline.draft_script        claude CLI
 │  type points  │                │                       │                      │
 │──────────────►│ POST /script   │                       │                      │
 │               │───────────────►│                       │                      │
 │               │                │ draft_script(text)    │                      │
 │               │                │──────────────────────►│                      │
 │               │                │                       │ gather(              │
 │               │                │                       │   claude(WRITER),    │──► subprocess.exec ──► stdout
 │               │                │                       │   claude(AESTHETIC)) │──► subprocess.exec ──► stdout
 │               │                │                       │ claude(CRITIC, segs) │──► subprocess.exec ──► stdout
 │               │                │ ScriptDraft           │                      │
 │               │                │◄──────────────────────│                      │
 │               │ 200  JSON      │                       │                      │
 │               │◄───────────────│                       │                      │
 │ see script    │ render review  │                       │                      │
 │◄──────────────│                │                       │                      │
```

### 6.2 Cue build

```
User       Chat UI       FastAPI                 build_cue              Claude  Playwright  ffmpeg
 │  approve  │              │                        │                     │        │         │
 │──────────►│ POST /cue    │                        │                     │        │         │
 │           │─────────────►│ asyncio.create_task ──►│                     │        │         │
 │           │              │ 200 {job_id}           │                     │        │         │
 │           │◄─────────────│                        │                     │        │         │
 │           │              │                        │ save plan.json      │        │         │
 │           │              │                        │ gather(N × SLIDE) ──►│        │         │
 │           │              │                        │◄────────────────────│        │         │
 │           │              │                        │ launch chromium ────────────►│         │
 │           │              │                        │ N × screenshot ────────────►│         │
 │           │              │                        │◄────────────────────────────│         │
 │           │              │                        │ N × silent clip ──────────────────────►│
 │           │              │                        │ concat → cue_video.mp4 ────────────────►│
 │           │              │                        │ write script.txt    │        │         │
 │           │ GET status   │                        │                     │        │         │
 │           │─────────────►│ reads JOBS[id]         │                     │        │         │
 │           │ 200 {…,done} │                        │                     │        │         │
 │           │◄─────────────│                        │                     │        │         │
 │ see cue   │              │                        │                     │        │         │
 │◄──────────│              │                        │                     │        │         │
```

### 6.3 Audio ingest (mixed sources)

```
User           Chat UI         FastAPI                Filesystem
 │  drag WAVs   │                │                          │
 │─────────────►│ POST /audio    │                          │
 │              │───────────────►│ save jobs/.../audio/*    │
 │              │                │─────────────────────────►│
 │              │                │ audio_status() reads dir │
 │              │                │◄─────────────────────────│
 │              │ 200 {audio:{…}}│                          │
 │              │◄───────────────│                          │
 │ click "auto" │                │                          │
 │─────────────►│ POST /auto-nrr │                          │
 │              │───────────────►│ to_thread(auto_narrate)  │
 │              │                │   for each missing slide:│
 │              │                │     subprocess `say` ───►│
 │              │                │   audio_status() ───────►│
 │              │ 200 {audio:{…}}│                          │
 │              │◄───────────────│                          │
```

### 6.4 Finalize

```
User       Chat UI       FastAPI            build_final          ffprobe   ffmpeg
 │   click  │              │                     │                 │         │
 │─────────►│ POST /final  │                     │                 │         │
 │          │─────────────►│ asyncio.create_task ►                 │         │
 │          │ 200 {job_id} │                     │                 │         │
 │          │◄─────────────│                     │                 │         │
 │          │              │                     │ load plan.json  │         │
 │          │              │                     │ for each i:     │         │
 │          │              │                     │   probe audio[i]►         │
 │          │              │                     │   build clip[i] ──────────►│
 │          │              │                     │ concat clips ─────────────►│
 │          │              │                     │ write video.mp4 │         │
 │          │ GET status   │                     │                 │         │
 │          │─────────────►│ reads JOBS[id]      │                 │         │
 │          │ 200 {…,done} │                     │                 │         │
 │          │◄─────────────│                     │                 │         │
 │ play MP4 │              │                     │                 │         │
 │◄─────────│              │                     │                 │         │
```

---

## 7. External dependencies

| Dependency        | Used by                | Required at      | Auth                              |
| ----------------- | ---------------------- | ---------------- | --------------------------------- |
| `claude` CLI      | every `pipeline.claude` | runtime          | Claude Code login (subscription)  |
| `ffmpeg` (PATH)   | both stages of pipeline | runtime          | none                              |
| `ffprobe` (PATH)  | both stages of pipeline | runtime          | none                              |
| `say` (macOS)     | `auto_narrate` only    | runtime, opt'l   | none — macOS built-in             |
| Playwright Python | `_screenshot_slide`    | runtime          | none                              |
| Chromium (PW)     | `_screenshot_slide`    | one-time install | none — local browser              |
| FastAPI, uvicorn  | `app.py`               | runtime          | none                              |
| python-multipart  | `app.py` (uploads)     | runtime          | none                              |

The `claude` CLI is the only network-bound dependency in the hot path —
all other tools are local processes.

---

## 8. Failure modes

| Failure                                      | Where surfaced                              | Recovery                                                                                                   |
| -------------------------------------------- | ------------------------------------------- | ---------------------------------------------------------------------------------------------------------- |
| `claude` CLI not logged in                   | `RuntimeError` from `pipeline.claude`       | Run `claude` interactively once to authenticate, then retry. Surfaced to UI as job error.                  |
| `claude` returns non-JSON or malformed JSON  | `ValueError` from `_extract_json`           | Fence-strip then balanced-block fallback; if both fail, job fails with the offending output in the message. |
| Claude exceeds 240 s                         | `RuntimeError` from `pipeline.claude`       | Job fails; user can click "Draft script" again.                                                            |
| Slide HTML references remote asset           | Playwright `set_content` may hang or error  | The slide-designer prompt explicitly forbids external assets; if it slips through, the screenshot still works (assets fail silently in chromium). |
| Audio file with wrong stem                   | `audio_status` reports `have_audio: false`  | Rename file to `slide_NN.<ext>` and re-poll.                                                               |
| `ffmpeg` missing                             | `FileNotFoundError` from subprocess         | Surfaced to UI; user installs Homebrew ffmpeg.                                                             |
| Server restart during cue/final              | In-flight `JOBS[id]` lost, partial files on disk | Restart, call cue/final again (idempotent: overwrites `jobs/<id>/slides`, work, video). For CLI use `--resume`. |
| Disk full while writing video                | `subprocess.run(check=True)` raises         | Job fails; user frees space and re-runs finalize.                                                          |
| Two browsers / two cli sessions hitting same job_id | Race on `audio/` dir                | We don't lock. Last writer wins. Acceptable for single-user local tool.                                    |

We deliberately don't retry Claude calls automatically. A `revise`
verdict from the critic is shown to the user; whether to re-run is the
user's call (this keeps the human in the quality loop).

---

## 9. Scaling and limits

This is a single-user, single-machine tool. The hard limits are:

- **Concurrency**: `JOBS` is an unbounded dict; nothing evicts old
  entries. For one user this is fine — a job is ~5 MB on disk plus the
  cue video — but a multi-tenant deployment would need a real store and
  a TTL.
- **Slide count**: each slide is one `claude` call, one Playwright page,
  one ffmpeg invocation. 6–8 slides is the sweet spot (~30–60 s for
  cue). 20+ slides will work but the user's subscription quota becomes
  the gating factor.
- **Video resolution**: hard-coded `1920 × 1080`. Changing
  `VIDEO_W`/`VIDEO_H` in `pipeline.py` is the only change needed; the
  slide-designer prompt is templated against the same constants.
- **Audio length**: `ffprobe` accepts arbitrary length; ffmpeg
  re-encodes audio to 192 kbit AAC. A 30-minute slide will work but
  defeats the format.

---

## 10. Decision log

These are the "why this, not that" calls that shaped the system.

### 10.1 `claude` CLI subprocess, not the Anthropic SDK
- **Decision**: every model call goes through `subprocess.exec("claude",
  "-p", ...)`.
- **Why**: lets the tool run against the user's Claude Code subscription
  with no `ANTHROPIC_API_KEY` and zero marginal cost per video.
- **Trade-off**: ~2 s CLI startup per call. For ~3–6 calls per video
  that's negligible. If we ever need true streaming or thousands of
  calls per session, swap the `pipeline.claude` function for the SDK.
- **Alternative considered**: anthropic-python SDK. Rejected because it
  would require the user to fund an API account in addition to their
  existing subscription.

### 10.2 Two stages with a disk handoff (not one monolithic build)
- **Decision**: `build_cue` writes `plan.json` and `slides/` and stops;
  `build_final` reads them and adds the audio.
- **Why**: lets the user re-record any subset of slides without redoing
  the expensive Claude calls or screenshots; lets the CLI's `--resume`
  pick up a job mid-flight; lets the human voice (the actual quality
  bottleneck) be added at the user's own pace.
- **Trade-off**: more disk I/O, two ffmpeg passes per slide. Worth it.

### 10.3 Human voice is the default, auto-narrate is opt-in
- **Decision**: the cue video is silent; audio uploads are the primary
  flow; `say`-based narration is a button.
- **Why**: synthetic narration is the single biggest quality drop in
  this format. The reference video (3Blue1Brown on neural networks)
  doesn't sound like a TTS demo, and neither should ours.
- **Trade-off**: more user effort. Mitigated by the auto-narrate option
  (which is good enough for previews) and by per-slide re-recording.

### 10.4 Slide HTML rendered with Playwright, not an SVG library or Manim
- **Decision**: slides are standalone HTML, screenshotted with Chromium.
- **Why**: Claude can write HTML far more naturally than it can write
  Manim scenes. HTML composes well (no per-frame logic), is trivial to
  preview, and renders deterministically when there are no external
  assets. We get free typography, gradients, SVG, and inline math via
  KaTeX/MathJax (when needed) without bringing a Python animation
  framework into scope.
- **Trade-off**: no real animation. Acceptable — the human voice
  carries the explanation, the slide is a static visual anchor. If we
  later want animation, the slide-designer prompt can output Lottie or
  CSS keyframes and we'd capture a video instead of a screenshot.

### 10.5 No on-screen subtitles
- **Decision**: subtitles are not burned onto the final video.
- **Why**: an earlier version baked a black subtitle bar into each
  slide via HTML injection. It worked but looked busy, fought the slide
  design, and added a fragile failure mode (text overflow on long
  lines). The script.txt cue sheet plus the user's own voice carries
  the same information.
- **Reversibility**: trivial — re-inject the subtitle bar in
  `pipeline._design_slide` and add an `_inject_subtitle` step before
  the screenshot.

### 10.6 Per-slide audio file (not one continuous take)
- **Decision**: the user records one file per slide, named
  `slide_NN.<ext>`.
- **Why**: each slide's duration is its audio's duration. No sync
  alignment, no Whisper transcript, no manual time-coding. Re-recording
  one slide doesn't disturb the rest.
- **Alternative considered**: one long take + ASR to find slide
  boundaries. Rejected — adds another ML dependency, fails ungracefully
  on accent/noise, and doesn't make re-recording easier.

### 10.7 In-process job dict, not a database
- **Decision**: `JOBS: dict[str, dict]` lives in the FastAPI process
  memory; the real artifacts live on disk.
- **Why**: single-user local tool. SQLite would be over-engineered;
  Redis would be absurd. The CLI's `--resume` works because the disk
  layout is the source of truth.
- **Trade-off**: if you ctrl-C the server while a cue is building, the
  progress messages are lost (you'd need to re-run). The artifacts that
  were already written are still on disk.

### 10.8 Two UIs against one pipeline
- **Decision**: `app.py` and `cli.py` are siblings, both importing
  `pipeline.*`. Neither has any business logic.
- **Why**: the web UI and the TUI cannot drift in behaviour because
  both call the same Python functions. New pipeline features show up
  in both UIs only via plumbing changes, not logic duplication.

### 10.9 macOS-only (today)
- **Decision**: `say` is in the dependency list, the README installs
  ffmpeg with Homebrew, and `open` is used for "open the video".
- **Why**: the maintainer is on macOS; cross-platform is YAGNI until
  someone else needs it.
- **Path to Linux**: replace `say` with `espeak`/`festival`, drop the
  `open` calls in favour of `xdg-open`, install ffmpeg with apt. Nothing
  in `pipeline.py` other than the `say` line is OS-specific.

---

## 11. Operations notes

### 11.1 Running locally

```bash
cd /Users/rashmi/Documents/content
.venv/bin/uvicorn app:app --reload --port 8000      # web UI
.venv/bin/python cli.py                              # interactive CLI
.venv/bin/python cli.py --auto-narrate               # unattended
```

The `--reload` flag is fine here because the server is single-user; in
a multi-user deploy you'd want gunicorn with a fixed worker count.

### 11.2 Logs

There's no structured logging. `pipeline.*` writes a `progress` list per
job; `app.py` echoes exceptions to stderr with `traceback.print_exc()`.
For dev that's adequate; for anything multi-user, wire `app.py`'s
exception handler to a real logger and tee `pipeline`'s `progress_cb`
into it.

### 11.3 Cleanup

`jobs/` grows monotonically. To reclaim disk:

```bash
rm -rf jobs/                 # full reset
# or
find jobs -maxdepth 1 -type d -mtime +14 -exec rm -rf {} +   # >14 days old
```

Nothing else holds state.

### 11.4 Updating the system prompts

All prompts live in `prompts.py`. Changes take effect on the next call —
no restart needed when `app.py` is started with `--reload`. Each prompt
is a single string constant; if you grow them past ~5 KB consider moving
to `.md` files loaded at import time.

### 11.5 Updating the slide aesthetic

`AESTHETIC_PICKER_PROMPT` controls the high-level palette + font
selection. `SLIDE_DESIGNER_PROMPT` is the one that produces the actual
HTML. Both should be edited together if you change the constraints (e.g.
adding a logo placement requirement).

### 11.6 Bumping ffmpeg / Playwright / Python

The pinned versions in `pyproject.toml` are the lower bounds. To
upgrade:

```bash
uv sync --upgrade
.venv/bin/playwright install chromium
```

Python is pinned to 3.11 in the venv; bumping to 3.12+ should be a
no-op (no version-specific syntax used).

---

## 12. Glossary

- **Segment** — one slide's worth of script: a title, a visual brief,
  and the narration text. A `ScriptDraft` is a list of segments plus an
  aesthetic and a critique.
- **Cue video** — the silent slideshow generated by `build_cue`. Each
  slide is shown for its narration-length estimate at 160 wpm. The user
  watches this while recording, or just to preview the visuals.
- **Final video** — the narrated MP4 produced by `build_final`. Slide
  durations match the user's audio durations exactly.
- **Job** — one run through the pipeline. Has a 10-hex `job_id` and a
  per-job directory under `jobs/`.
- **Auto-narrate** — the optional macOS `say` fallback that fills in
  audio for slides the user hasn't recorded.
- **Plan** — `plan.json` in the per-job directory: the approved script
  (topic + aesthetic + segments). The contract between `build_cue` and
  `build_final`.
