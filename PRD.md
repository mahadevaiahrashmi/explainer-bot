# Explainer Bot — Product Requirements Document

| Field         | Value                                              |
| ------------- | -------------------------------------------------- |
| Product       | Explainer Bot                                      |
| Owner         | @mahadevaiahrashmi                                 |
| Status        | v0.1 (single-user local tool, public on GitHub)    |
| Last revised  | 2026-05-26                                         |
| Repo          | <https://github.com/mahadevaiahrashmi/explainer-bot> |

Related docs:
[README](./README.md) ·
[PRODUCT_DESIGN](./PRODUCT_DESIGN.md) ·
[SYSTEM_DESIGN](./SYSTEM_DESIGN.md) ·
[TESTING](./TESTING.md)

---

## 1. TL;DR

A single-user desktop tool that turns a few rough points about a concept
into a finished, narrated explainer video — in the style of 3Blue1Brown's
[*But what is a neural network?*](https://www.youtube.com/watch?v=jx6FevmKJGg).
The user types rough points, the bot writes a script, designs each slide,
shows the user the slides for editing, then assembles a video with the
user's own recorded voice (or a TTS fallback).

The product exists because making one of these videos by hand takes 4–8
hours per minute of finished video; the bot collapses that to roughly the
time it takes the user to read the script aloud, plus a few minutes of
review.

---

## 2. Problem statement

### The status quo

Making an explainer video in the 3B1B / Veritasium / Kurzgesagt style
requires the maker to be good at four different crafts:

1. **Writing**: condense a concept into clear, undergrad-readable prose
   with vivid analogies — without sounding like a textbook.
2. **Design**: produce slides that visualise the idea, not just bullet
   points of the narration.
3. **Animation / video assembly**: tools like Manim, After Effects, or
   Premiere have steep learning curves and slow iteration loops.
4. **Voice**: deliver narration that sounds curious and human, with the
   right pacing and emphasis.

Most people who could explain an idea well are blocked on (2), (3), and
(4). The result: knowledge that *would* make a great explainer never gets
made into one.

### What changes if this exists

A subject-matter expert can take a half-page of rough points and have a
~1-minute publishable video in 15–30 minutes of focused work, most of
which is reading the script aloud once. They never need to learn Manim or
After Effects. They never write CSS. The bot handles the writing, design,
and assembly; the human still owns the voice, the editorial judgement,
and any creative tweaks to the slide HTML.

### Why now

Three things have to be true at once for this to be feasible, and they
all are:

- **Frontier LLMs can write good explainer scripts.** Claude-Sonnet-4.5
  and equivalents produce narration that passes a "first-year-CS-
  undergrad-friendly + has analogies + has wonder" critique with very
  little prompt scaffolding.
- **Frontier LLMs can write standalone presentation HTML.** Same models,
  given the right system prompt, write 1920×1080 self-contained slides
  with inline CSS and SVG that are visually credible.
- **Headless Chromium + ffmpeg are free and stable.** No paid render
  pipeline; the entire build is local.

---

## 3. Users and personas

We name three personas. The product is built primarily for *Sara*; the
other two are accommodated but not the design target.

### Sara — the explainer-curious expert (primary)

- **Who**: a working PhD student, software engineer, or domain expert
  (10+ years deep on something interesting).
- **Has**: strong intuitions, a few rough notes, no video toolchain.
- **Wants**: to publish a short video on YouTube / X / a blog post so
  the rest of her community sees the idea clearly.
- **Doesn't want**: to learn Manim, After Effects, or graphic design.
  Already tried once, got frustrated, gave up.
- **Will accept**: a chat-style UI, a few minutes of slide tweaking, and
  one continuous voice recording.

### Carlos — the teacher (secondary)

- **Who**: a university lecturer or high-school teacher.
- **Has**: lecture notes already written; needs to flip a topic into a
  short explainer for asynchronous viewing.
- **Wants**: to convert each lecture concept to a 1–3 minute video in
  under an hour of work.
- **Constraints**: school laptops, no API budget, often offline. Needs
  the Ollama / subscription path, not a paid API.

### Riya — the developer (tertiary)

- **Who**: an engineer cloning the repo to learn how the pipeline is
  put together, possibly to extend it.
- **Wants**: clean code, swappable backends, a system-design doc.
- **Constraints**: macOS or Linux; comfortable in a terminal.

Implications for design:

- **Sara**: web UI is the primary surface; chat-style flow with strong
  defaults beats forms with many knobs.
- **Carlos**: must work fully offline (Ollama backend) and must not cost
  anything per video.
- **Riya**: pipeline must be importable as a Python module, the
  scaffolding must be readable, and the system-design doc must be
  accurate.

---

## 4. User goals (jobs-to-be-done)

In priority order:

1. **JTBD-1**: *"When I have a half-formed idea I want explained well,
   turn it into a watchable video, so my audience gets the insight
   without me having to spend a weekend on it."*
2. **JTBD-2**: *"When I see the bot got the script wrong, let me fix it
   in plain English, so I don't have to learn the bot's internals."*
3. **JTBD-3**: *"When I see a slide that has overlapping text or some
   layout issue, let me fix it without writing CSS."*
4. **JTBD-4**: *"When I want my own voice on the video, let me record
   per-slide audio in any common format and assemble cleanly."*
5. **JTBD-5**: *"When I don't want my voice on this one, let the bot
   narrate so I can preview what the final video would feel like."*
6. **JTBD-6**: *"When the cost of running it matters, let me pick a
   free local model; when it doesn't, let me pick the best cloud model."*

---

## 5. Success metrics

### Primary (what we'd track if there were analytics)

- **Time-to-first-video (TTFV)**: median wall-clock from app open to
  downloaded MP4 for a Sara-equivalent user.
  - **Target**: ≤ 30 minutes for a ~1-minute video, including recording.
- **Approval rate of first-draft script**: fraction of users who accept
  the script without editing any segment.
  - **Target**: ≥ 60%.
- **Slide-fix invocation rate**: fraction of slides where the user
  clicks "ask bot to fix this slide" or edits HTML directly.
  - **Healthy band**: 10–30%. Above 30% means the slide designer
    prompt needs tightening; below 10% might mean users don't realise
    they can edit.

### Secondary

- **% videos that use the user's own voice** vs auto-narrate. Higher =
  the product is being used for "real" output, not just previews.
- **Backend mix**: what fraction of videos use `claude_cli` /
  `ollama` / `llm`. Confirms whether the "free local" path is
  actually used or whether everyone falls back to paid cloud.
- **Mean number of slides per video**: helps tune the writer prompt
  (currently targets 4–8 segments).

### Anti-goals (metrics we deliberately don't optimise for)

- Engagement / time-on-site: this isn't a content platform.
- Number of videos per user per day: bursty creative work, not
  high-frequency throughput.
- Generation latency under 10 s: 30–60 s for a script + slides is
  acceptable given the quality bar.

---

## 6. Functional requirements

### 6.1 Must-have (v0.1, shipped)

| ID    | Requirement                                                                                                          |
| ----- | -------------------------------------------------------------------------------------------------------------------- |
| FR-1  | User pastes rough points (free text) and gets back a script broken into 4–8 slide segments.                          |
| FR-2  | Each segment has a title, a key-visual brief, and 2–5 sentences of narration.                                        |
| FR-3  | A reviewer agent scores the script on three criteria (understandability, analogies, wonder) and returns notes.       |
| FR-4  | A picker agent chooses one visual aesthetic (palette + font) for the whole video.                                    |
| FR-5  | The user can edit any title / visual brief / narration before slides are designed.                                   |
| FR-6  | The bot generates standalone HTML for each slide (1920×1080, no external assets).                                    |
| FR-7  | The user can preview each slide's rendered output side-by-side with its source HTML, and edit the HTML.              |
| FR-8  | The user can request a slide fix in plain English ("title overlaps diagram") and the bot regenerates the HTML.       |
| FR-9  | The bot screenshots all slides via headless Chromium and assembles a silent "cue" video at narration-length pacing.  |
| FR-10 | The bot exports a `script.txt` cue sheet with per-slide timestamps and the narration text.                           |
| FR-11 | The user can upload per-slide audio in any common format (.wav, .mp3, .m4a, .aiff, ...) and re-upload individually.  |
| FR-12 | The bot can auto-narrate any or all slides via macOS `say` for users who don't want to record.                       |
| FR-13 | The bot assembles a final MP4 where each slide's duration matches its audio file's duration.                         |
| FR-14 | The user can switch LLM backends (`claude_cli`, `ollama`, `llm`) per request via a UI picker, no restart required.   |
| FR-15 | The user can resume any job by ID from the CLI without re-running design/screenshot steps.                           |
| FR-16 | Same flow available via web UI (FastAPI + chat) AND interactive terminal UI (cli.py).                                |
| FR-17 | A non-interactive `python cli.py --auto-narrate` runs the full pipeline unattended for hands-off use.                |

### 6.2 Should-have (v0.2, planned)

| ID    | Requirement                                                                                                          | Tracking issue |
| ----- | -------------------------------------------------------------------------------------------------------------------- | -------------- |
| SR-1  | Cloud TTS option (ElevenLabs / OpenAI) for users who want better synthetic narration than `say`.                     | [#4](https://github.com/mahadevaiahrashmi/explainer-bot/issues/4) |
| SR-2  | Unit + API tests so changes can be made with confidence.                                                             | [#1](https://github.com/mahadevaiahrashmi/explainer-bot/issues/1), [#2](https://github.com/mahadevaiahrashmi/explainer-bot/issues/2) |
| SR-3  | An "Approve all and finalize" one-click path from the slide-edit stage straight to the final video.                  | —              |

### 6.3 Could-have (v1.0)

- Re-runnable critic with thresholds (auto-redraft if any score < 4).
- Voice-cloning option (user's own voice via TTS) for slides they
  didn't get to record.
- Multi-voice / dialogue scripts.
- A "library" of past videos / scripts for the user to revisit and
  re-export.

### 6.4 Won't-have (v1, explicitly)

- **Animation**. Slides are static screenshots; no Manim integration.
- **Cloud multi-tenancy**. Single-user local tool by design — no auth,
  no quotas, no per-user storage isolation.
- **Mobile / tablet UI**. Web UI is desktop-first; mobile is best-
  effort.
- **Video editing surface**. We don't expose a timeline; per-slide
  duration is controlled by audio length, period.
- **Built-in upload to YouTube / X / Vimeo**. User downloads the MP4
  and uploads themselves.

---

## 7. Non-functional requirements

| Area              | Requirement                                                                                                                              |
| ----------------- | ---------------------------------------------------------------------------------------------------------------------------------------- |
| **Performance**   | Script + critique + aesthetic in ≤ 90 s on a Claude-Sonnet-4.5 backend. Slide design for 6 slides in parallel in ≤ 90 s. Cue video assemble ≤ 30 s. Final assemble ≤ 15 s. |
| **Reliability**   | A failed model call surfaces a job-level error with a useful message; the user can retry without losing prior stages.                    |
| **Resumability**  | If the server is killed mid-job, the user can resume from disk via `cli.py --resume <job_id>` without re-paying any Claude calls.        |
| **Offline**       | The Ollama backend works with no internet. Slide rendering uses no remote assets.                                                        |
| **Cost**          | Zero marginal cost on the `claude_cli` (subscription) and `ollama` paths. ≤ $0.05 per video on the `llm` cloud path with default model.  |
| **Privacy**       | No telemetry. All artifacts live under `jobs/<id>/` on the user's machine. The Ollama backend never leaves the machine.                  |
| **Accessibility** | Web UI hits AA contrast on the dark theme; uses semantic HTML; keyboard-navigable. Not yet screen-reader tested.                         |
| **Portability**   | macOS today (`say`, `open`). Linux feasible (swap `say` for `espeak`, `open` for `xdg-open`); see SYSTEM_DESIGN §10.9.                   |
| **Security**      | Server binds 127.0.0.1 by default. Slide HTML rendered in a sandboxed iframe in the UI. Path traversal defeated on audio upload.         |
| **Internationalisation** | English-only narration today. The writer/critic prompts are language-agnostic in principle; would need per-language `say` voice. |

---

## 8. Constraints & assumptions

### Constraints

- **macOS-only `say`**. The auto-narrate fallback only works on macOS.
  Linux / Windows users have to pick a different audio path.
- **Single-user**. No multi-tenant story; the in-process `JOBS` dict
  is fine for one user, fragile for ten.
- **Subscription is opaque**. The `claude_cli` backend can be rate-
  limited by Claude Code at any time; we can't see or surface those
  limits.
- **No streaming**. The model call is request/response only; long
  scripts feel like staring at a spinner.

### Assumptions

- The user has a modern macOS laptop with Homebrew, Python 3.11+, and
  either Claude Code installed *or* an API key.
- The user is willing to record their own voice (or accept synthetic
  narration as the obvious quality tradeoff).
- A 1080p 30 fps MP4 is the right output format for the user's
  destination platforms (YouTube, X, blog embeds).
- The user wants slides that are visually restrained, not flashy. The
  3B1B aesthetic is the north star — *not* TikTok-style motion.

---

## 9. Risks & mitigations

| Risk                                                                       | Likelihood | Impact | Mitigation                                                                                  |
| -------------------------------------------------------------------------- | ---------- | ------ | ------------------------------------------------------------------------------------------- |
| Frontier model quality regresses on the slide-design prompt                | Medium     | High   | Per-slide HTML edit + "ask bot to fix this slide" gives the user a manual escape hatch.     |
| User's Claude Code subscription quota runs out mid-job                     | Low        | Medium | `BACKEND=` env var + UI picker lets the user switch to Ollama or a cloud key per call.      |
| Auto-narrate via `say` produces unusably bad audio for a serious video     | Certain    | Low    | We've made human voice the default; auto-narrate is positioned as "preview only" in copy.   |
| Slide layouts overflow the 1920×1080 frame                                 | Medium     | Medium | Live preview at native resolution; "ask bot to fix" feedback loop; the slide-designer prompt explicitly constrains to the frame. |
| User loses recordings due to a re-run wiping `jobs/<id>/audio/`            | Low        | High   | `build_cue` deletes the old job dir if you call it again with the same id — call out in docs and require explicit overwrite intent. Today the safe path is to use a *new* job for re-takes. |
| Smaller / local models return malformed JSON                               | High (on Ollama small models) | Medium | `_extract_json` has a balanced-block fallback parser; SYSTEM_DESIGN §8 documents the failure mode. |

---

## 10. Out-of-scope & explicit non-goals

- **Editing the final video as a timeline.** No clip ordering, no
  transitions, no cuts inside a slide. If the user wants that, the
  expectation is they export the MP4 and finish in iMovie/DaVinci.
- **Real animation.** A still image per slide is the design.
- **Hosting / publishing.** No YouTube uploader, no link shortener, no
  thumbnails.
- **Collaboration.** No comments on segments, no review workflow, no
  shared projects.
- **Analytics.** Zero phone-home. Even error rates are not reported.

---

## 11. Open questions

| #   | Question                                                                                                          | Owner | Resolves by |
| --- | ----------------------------------------------------------------------------------------------------------------- | ----- | ----------- |
| Q1  | Should we cap the number of slides? Long videos (20+ slides) take long Claude / long render. Soft warn at 12?     | TBD   | v0.2        |
| Q2  | Should the critic auto-redraft when scores < 4 on any axis, or always defer to the user?                          | TBD   | v0.2        |
| Q3  | Do we expose the writer / critic prompts in the UI for power users to tweak per-job?                              | TBD   | v1.0        |
| Q4  | Voice cloning: ethical/legal stance if the user uploads someone else's voice as a seed?                           | TBD   | v1.0        |
| Q5  | Do we ship a Linux port (espeak, xdg-open) or wait for community demand?                                          | TBD   | v0.3        |
| Q6  | Cue video pacing currently uses fixed 160 wpm. Should this be configurable per video? Per user?                   | TBD   | v0.2        |

---

## 12. Release strategy

- **v0.1 — Today.** Single-user local. macOS-only. Published on GitHub
  as a working tool, not a polished product. README is the install
  guide.
- **v0.2 — Quality of life.** Better TTS (#4), tests (#1, #2), pacing
  configurability, Q1/Q2/Q6 resolved.
- **v0.3 — Reach.** Linux port. Maybe a Docker image for users without
  Homebrew.
- **v1.0 — Polish.** Voice cloning, library of past videos,
  one-click publish workflow. Re-evaluate single-tenant assumption.

No date commitments. This is a tools project, not a product company.

---

## 13. Appendix

### A. Reference video (the quality bar)

[*But what is a neural network?* — 3Blue1Brown](https://www.youtube.com/watch?v=jx6FevmKJGg)
is the explicit target for what "good" looks like:

- **Narration**: every sentence is undergrad-readable; no undefined jargon.
- **Pacing**: ~160 words/min, with natural pauses after analogies land.
- **Visuals**: each slide has one focal idea, rendered in restrained
  navy/blue/white; the *idea* is what carries the slide, not motion.
- **Sense of wonder**: the writer is fascinated by the subject and the
  viewer can tell — not through hype words, but through the IDEAS
  landing.

The `CRITIC_PROMPT` in `prompts.py` codifies these as three review axes:
understandability, analogies, wonder.

### B. Glossary

- **Segment** — one slide's worth of script.
- **Cue video** — silent slideshow used as a recording cue.
- **Plan** — `plan.json`: the approved script after the review step.
- **Job** — one trip through the pipeline; has an id and a directory.
- **Backend** — which LLM the bot talks to (`claude_cli` / `ollama` / `llm`).

### C. Document conventions

- "Must / should / could / won't" follows RFC 2119.
- Tracking issues link to <https://github.com/mahadevaiahrashmi/explainer-bot/issues>.
- This PRD is paired with [PRODUCT_DESIGN.md](./PRODUCT_DESIGN.md)
  (UX), [SYSTEM_DESIGN.md](./SYSTEM_DESIGN.md) (engineering), and
  [TESTING.md](./TESTING.md) (test + UAT).
