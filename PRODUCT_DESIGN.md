# Explainer Bot — Product Design

| Field         | Value                                              |
| ------------- | -------------------------------------------------- |
| Surface       | Web UI (FastAPI + vanilla HTML/CSS/JS) + Terminal UI |
| Design owner  | @mahadevaiahrashmi                                 |
| Last revised  | 2026-05-26                                         |

Related docs:
[README](./README.md) ·
[PRD](./PRD.md) ·
[SYSTEM_DESIGN](./SYSTEM_DESIGN.md) ·
[TESTING](./TESTING.md)

---

## 1. Design principles

These six rules trade off everything else.

1. **Strong defaults, no required configuration.** A first-time user
   should be able to type rough points and click one button. Backend,
   model, aesthetic, slide count — all picked sanely without asking.
2. **The bot's work is provisional; the user always has final say.** Every
   AI output (script, slide HTML, narration estimate) is editable, and
   "ask the bot to fix this" is one click away. The user never has to
   accept what they don't agree with.
3. **Show the user the actual thing, not a proxy.** Slide previews are
   rendered at native 1920×1080 so the layout, fonts, and overlaps are
   *exactly* what gets screenshotted. No "this is approximately what it
   will look like" UI.
4. **One forward path, with cheap retreat.** The flow is linear (input →
   script → slides → cue → audio → final). At every stage there's a
   "back" button; going back never destroys work in later stages unless
   the user explicitly redrafts.
5. **Human voice is the default; synthetic narration is positioned as a
   preview tool.** The pacing, the script.txt cue sheet, the per-slide
   audio model — everything is designed for recording-along.
6. **Stay out of the way.** No marketing copy, no testimonials, no
   feature tour. The empty state is just the input textarea.

---

## 2. Personas (design-relevant detail)

See [PRD §3](./PRD.md#3-users-and-personas) for the full personas. Two
things matter for design:

- **Sara has no toolchain.** She'll bail if the install instructions
  exceed three commands or if the first run requires picking from a
  config dropdown. The UI's empty state and the README's quickstart
  carry the weight of first-run experience.
- **Carlos works on a school laptop, offline, no API key.** The Backend
  picker must surface Ollama as a first-class peer of Claude, not a
  fallback footnote. The error state when the chosen backend isn't
  installed must point to the install command, not a stack trace.

---

## 3. The user journey

### 3.1 Happy path (Sara, web UI)

```
   1. Open  http://localhost:8000
   2. Type rough points  →  click "Draft script"          ~45 s wait
   3. Read critique, scan segments, edit one narration
                                                          ~3  min
   4. Click "Approve script → design slides"              ~45 s wait
   5. Tab through slides, spot-check, tweak one HTML
      header, click "Re-render"                           ~3  min
   6. Click "Build cue video"                             ~15 s wait
   7. Watch cue, download script.txt                      ~1  min
   8. Open QuickTime, record slide_00.wav … slide_05.wav  ~7  min
   9. Drag-drop into the upload area                      ~10 s
  10. Click "Build final video"                           ~10 s wait
  11. Play in-page, download MP4                          ~30 s
                                                          ─────────
                                                          ~15 min
```

### 3.2 Hands-off path (preview-only, CLI)

```
  echo "What is recursion? - matryoshka analogy ..." | \
    .venv/bin/python cli.py --auto-narrate
                                                          ~3 min total
```

Pure preview — final video plays automatically when done. No
recording, no manual approval.

### 3.3 Iteration path (Sara fixing a bad slide)

```
   1. On the slide-edit stage, click the slide's tab.
   2. Spot the issue in the preview: the title overlaps the diagram.
   3. Click "Report issue / ask bot to fix" → describe in plain English.
   4. Wait ~30 s, the textarea + preview update with the fix.
   5. If still wrong, repeat with more specific feedback, or hand-edit
      the HTML in the textarea and "Re-render this slide".
   6. When all slides are right, "Build cue video".
```

This loop is the product's main differentiator from a one-shot
generator. Fast, plain-English iteration on visual issues.

---

## 4. Information architecture

The web UI is a single page with five sequential stages, gated by
buttons. State persists in JS globals (`SCRIPT`, `JOB_ID`, `SLIDES`,
`CURRENT_SLIDE`); reloading the page resets but the server's `jobs/`
directory keeps every artifact.

```
┌────────────────────────────────────────────────────────┐
│ Header  (logo • flow caption)                          │
├────────────────────────────────────────────────────────┤
│ Model picker  (backend dropdown • model input • badge) │ ← persistent
├────────────────────────────────────────────────────────┤
│                                                        │
│   ONE of five stage sections at a time:                │
│                                                        │
│   • stage-input    rough-points textarea               │
│   • stage-review   critique + editable segments        │
│   • stage-slides   tabs + HTML editor + live preview   │
│   • stage-record   cue video + script + audio upload   │
│   • stage-final    final MP4 + download                │
│                                                        │
└────────────────────────────────────────────────────────┘
```

Only one stage is `.active` at a time. The picker is always visible
because changing it affects calls in every stage.

---

## 5. Stage-by-stage screens

### 5.1 Stage 1 — Input

**Purpose**: capture the user's rough points.

```
┌──────────────────────────────────────────────────────┐
│ Give me rough points or a thought to explain.        │
│ ┌──────────────────────────────────────────────────┐ │
│ │  (textarea, 180 px tall, placeholder shows       │ │
│ │   three example topics)                          │ │
│ │                                                  │ │
│ └──────────────────────────────────────────────────┘ │
│                                                      │
│ [ Draft script ]   Claude will write a narration,    │
│                    pick a slide aesthetic, and       │
│                    critique its own work (~30–60s).  │
└──────────────────────────────────────────────────────┘
```

**Decisions**:
- Single textarea, no formatting toolbar. Bullet points work because
  the writer prompt handles them; no need to teach the user a syntax.
- Button copy says what happens next, not "Submit".
- Hint text sets time expectation so the user doesn't think it's
  hung at 30 s.

### 5.2 Stage 2 — Review

**Purpose**: let the user accept, edit, or redraft the bot's output
before any visual work happens (visuals are the expensive part).

```
┌──────────────────────────────────────────────────────┐
│ Slide aesthetic — "Chalkboard Recursion"             │
│   Dark slate background with hand-drawn feeling…     │
│   ▢ ▢ ▢ ▢ ▢  (palette swatches)                      │
├──────────────────────────────────────────────────────┤
│ Reviewer critique     [approve]                      │
│   understandability: 5/5   analogies: 4/5  wonder: 5/5│
│   • Consider clarifying the base case in segment 2.  │
├──────────────────────────────────────────────────────┤
│ Script — edit any field before building cue video    │
│ ┌──────────────────────────────────────────────────┐ │
│ │ 1. [ A Function That Calls Itself              ] │ │
│ │    visual: A function box f(n) with…             │ │
│ │    narration: Imagine you write a function…      │ │
│ │ 2. ...                                           │ │
│ └──────────────────────────────────────────────────┘ │
│                                                      │
│ [ Approve script → design slides ]  [← Rewrite ]     │
└──────────────────────────────────────────────────────┘
```

**Decisions**:
- The critique is shown with the verdict as a coloured pill (`approve` =
  green, `revise` = yellow). Scores below 4 don't *block* the user —
  they just signal that the user may want to fix things.
- Every segment field is an inline edit. No modal, no separate edit
  page. The bot's drafts are starting points, not final output.
- The aesthetic preview shows palette swatches so the user can imagine
  the slide before clicking forward.

### 5.3 Stage 3 — Slides (the editor)

**Purpose**: review and edit the generated HTML for each slide; this is
the stage where text overlap or visual bugs get caught.

```
┌──────────────────────────────────────────────────────────────┐
│ Slides — preview, edit HTML, re-render                       │
│ Each slide is a standalone 1920×1080 HTML document. Click a  │
│ tab to view it. Edit on the left, click Re-render…           │
│                                                              │
│ [ 1. A Function That… ][ 2. The Russian Doll ][ 3. … ]       │
│ ────────────────────────────────────────────────────         │
│                                                              │
│ Slide 1 HTML — A Function That Calls Itself                  │
│ ┌─────────────────────────────────┐  ┌────────────────────┐  │
│ │ <!doctype html>                 │  │ Live preview       │  │
│ │ <html><body style="…1920×1080"> │  │ (full slide        │  │
│ │   …                             │  │  scaled to fit)    │  │
│ │ </body></html>                  │  │                    │  │
│ │ (monospace textarea, ~600 px)   │  │  ┌──────────────┐  │  │
│ └─────────────────────────────────┘  │  │ slide preview│  │  │
│                                      │  │  iframe (CSS │  │  │
│ [ Re-render this slide ]             │  │  scaled,     │  │  │
│ [ Revert to bot's version ]          │  │  ≤600 px)    │  │  │
│ [ Report issue / ask bot to fix ]    │  └──────────────┘  │  │
│                                      └────────────────────┘  │
│                                                              │
│ [ Build cue video ]   [← Back to script ]                    │
└──────────────────────────────────────────────────────────────┘
```

**Decisions**:

- **Tab bar** instead of a long scroll: keeps the editor visible
  without paging.
- **Side-by-side editor + preview** mirrors every other code-with-
  preview tool the user knows (Codepen, RegExr, MDN playground).
- **Native-resolution iframe with CSS scale**: the preview is exactly
  what gets screenshotted. The scale is automatic via JS so changing
  window size always refits.
- **Dirty indicator** (●) on the tab makes it obvious when an unsaved
  edit exists.
- **"Report issue / ask bot to fix"** is collapsed by default — it's a
  power-user escape hatch, shouldn't dominate the primary "Re-render"
  action.
- **PNG link** under the preview lets the user pop the rendered PNG in
  a new tab for true 1:1 inspection.

### 5.4 Stage 4 — Cue + record

**Purpose**: hand off to the user for voice recording; provide both the
cue video and the script as artifacts.

```
┌────────────────────────────────────────────────────────────┐
│ Cue video    (job aae6a72695)                              │
│ ┌────────────────────────────────────────────────────────┐ │
│ │ progress log: Building silent cue video... Cue ready.  │ │
│ └────────────────────────────────────────────────────────┘ │
│ ┌──────────────────── video player ────────────────────┐  │
│ [ Download cue video ] [ Download script.txt ]             │
├────────────────────────────────────────────────────────────┤
│ Script — read each slide into a separate audio file        │
│ ┌────────────────────────────────────────────────────────┐ │
│ │ # What is recursion?                                   │ │
│ │ SLIDE 1/6  (0:00 → 0:18, ~17.9s)  slide_00.wav         │ │
│ │ ...                                                    │ │
│ └────────────────────────────────────────────────────────┘ │
├────────────────────────────────────────────────────────────┤
│ Upload your recordings                                     │
│ Drop your audio files here, or click to choose.            │
│ ┌────────────────────────────────────────────────────────┐ │
│ │  drop zone                                             │ │
│ └────────────────────────────────────────────────────────┘ │
│ [ Auto-narrate missing ] [ Auto-narrate everything ]       │
│                                                            │
│   #  slide title       expected     status     │
│   1  A Function...     slide_00.<>  [missing]              │
│   2  The Russian Doll  slide_01.<>  [missing]              │
│   ...                                                      │
│                                                            │
│ [ Build final video ]   [← Back to slides ]                │
└────────────────────────────────────────────────────────────┘
```

**Decisions**:

- **Cue video is the artifact the user records along to.** Showing it
  in-page (not a download) lets them preview pacing before recording.
- **Script.txt is downloadable as plain text** so the user can print
  it or open in their preferred reader during recording.
- **Drop zone + per-slide table** combines the casual "just drop files"
  affordance with explicit per-slide status feedback (red = missing,
  green = present + duration).
- **Auto-narrate buttons** are right next to the drop zone, framed as
  an alternative ("or use…"). The "overwrite" variant has a confirm
  prompt because it's destructive of recordings.
- **"Build final video" is disabled until every slide has audio.**
  Removes the "why did it fail?" failure mode.

### 5.5 Stage 5 — Final

**Purpose**: deliver the MP4 and offer a clear restart.

```
┌────────────────────────────────────────────────────────────┐
│ Building final video    (job aae6a72695)                   │
│ ┌────────────────────────────────────────────────────────┐ │
│ │ slide 1/6 — 15.4s                                      │ │
│ │ slide 2/6 — 22.6s                                      │ │
│ │ ...                                                    │ │
│ │ Done.                                                  │ │
│ └────────────────────────────────────────────────────────┘ │
├────────────────────────────────────────────────────────────┤
│ Final video                                                │
│ ┌──────────────────── video player ────────────────────┐   │
│ [ Download MP4 ]   [ Make another ]                        │
└────────────────────────────────────────────────────────────┘
```

**Decisions**:
- The in-page player plays the final immediately so the user can
  watch + decide whether to re-record any slides.
- "Make another" resets all JS state but doesn't touch `jobs/` on
  disk — old videos stay browsable via the file system or `cli.py
  --resume`.

---

## 6. Persistent UI elements

### 6.1 Model picker (top strip, every stage)

```
┌──────────────────────────────────────────────────────────────────┐
│ Backend: [(server default) ▾]  Model: [claude-sonnet-4-5      ]  │
│                                Server default: claude_cli (auto) │
└──────────────────────────────────────────────────────────────────┘
```

**Decisions**:
- **Always visible**, even mid-flow, because changing it should affect
  the next call (e.g. designing with a fast cheap model, fixing with
  a smarter one).
- **"(server default)"** as the first option means a user who never
  touches the picker gets whatever the operator configured at startup.
- **The badge** ("Server default: claude_cli (auto)") removes the
  mystery of what the default actually resolves to.
- **Free-text model input** because hard-coding the model list goes
  stale every few weeks; the `llm` CLI knows hundreds of models.

### 6.2 Stage banner / breadcrumb

Implicit, not rendered explicitly: the header subtitle
*"rough points → script → slide HTML → cue video → your voice → final video"*
serves as a perpetual roadmap.

---

## 7. Visual design

### 7.1 Palette

| Token         | Hex       | Use                            |
| ------------- | --------- | ------------------------------ |
| `--bg`        | `#0d1117` | Page background                |
| `--panel`     | `#161b22` | Card backgrounds               |
| `--panel-2`   | `#1f2630` | Inset backgrounds (segments)   |
| `--text`      | `#e6edf3` | Body text                      |
| `--muted`     | `#8b949e` | Hint text, labels              |
| `--accent`    | `#58a6ff` | Primary buttons, links         |
| `--good`      | `#3fb950` | Approve verdict, present pill  |
| `--warn`      | `#d29922` | Revise verdict, dirty marker   |
| `--bad`       | `#f85149` | Errors, missing pill, danger   |
| `--border`    | `#30363d` | Panel borders, dividers        |

Inherited from GitHub's dark theme intentionally. Familiar to the
developer audience; doesn't compete with the colourful slide previews.

### 7.2 Typography

- **System font stack**: `-apple-system, BlinkMacSystemFont, "Segoe UI",
  sans-serif`. Base size 15 px, line-height 1.5.
- **Monospace**: `ui-monospace, SF Mono, Menlo, monospace`. Used for
  the script.txt preview, the HTML textarea, and inline `code` spans.
- No web fonts — keeps the UI offline-capable and avoids FOUT.

### 7.3 Components

| Component         | Used for                                      | Notes                                  |
| ----------------- | --------------------------------------------- | -------------------------------------- |
| `.panel`          | Cards on every stage                          | 10 px radius, 1 px border, 16 px pad.  |
| `.row`            | Horizontal button + hint groups               | flex with 10 px gap; wraps on narrow.  |
| `.segment`        | Editable script chunk                         | Nested panel, slightly darker inset.   |
| `.slide-tabs button` | Slide tab bar items                        | Active tab is accent-coloured.         |
| `.file-drop`      | Audio upload zone                             | Dashed border, hover/drag affordance.  |
| `.verdict`        | Critic verdict pill                           | Two colour variants: approve / revise. |
| `.pill`           | Audio status (present + duration / missing)   | Two colour variants: ok / missing.     |

### 7.4 Layout

- Single column, `max-width: 1100px`, centred. Slide-edit stage breaks
  into a 2-column grid only inside its panel.
- 24 px page padding; 16 px between panels; 12 px between inline rows.
- No fixed/sticky header — page scrolls naturally.

### 7.5 Iconography

- None. All affordance is conveyed by text labels and colour. (One
  exception: the ✓ / · marks in the CLI's audio status, where the
  terminal denies us colour-as-affordance.)

---

## 8. Interaction patterns

### 8.1 Long-running work

Two patterns:

- **Synchronous (≤ 90 s)**: `POST /script`, `POST /design`,
  `POST /slide-fix`. The button shows a "..." state and the hint text
  becomes "Drafting... 30–60s." No spinner — the hint *is* the spinner.
- **Async with poll (≥ 30 s, often longer)**: `POST /cue`,
  `POST /render-cue`, `POST /finalize`. The UI shows a live progress
  log fed by `GET /jobs/{id}/status` polled every 1500 ms.

### 8.2 Editing

- **Inline**: all script-segment fields, the slide HTML textarea, the
  audio status table.
- **Modal-like collapse**: the "Report issue / ask bot to fix" panel
  expands in place; it's not a modal — modals break the flow.
- **No autosave for the textarea** — the user has explicit "Re-render"
  / "Build cue video" buttons that persist. We do show a "● unsaved"
  marker on the tab so it's clear when state diverges.

### 8.3 Destructive actions

- **Delete audio for slide N**: confirmed by the table being live; no
  modal, the row updates immediately. Re-uploading is one drag away.
- **Auto-narrate everything (overwrite)**: explicit `confirm()` dialog
  because it deletes user recordings.
- **"Make another"**: clears JS state only — disk artifacts remain.

### 8.4 Errors

- **Per-request**: a red row at the bottom of the relevant panel with
  the message verbatim. No "Something went wrong" wrappers; the user
  needs the actual reason (e.g. backend not configured).
- **Per-job (async)**: progress log gets `\n\nError: <message>` appended.
  The progress log stays scrollable for after-the-fact debugging.

### 8.5 Empty states

- **First load**: stage-input is the empty state. Placeholder text in
  the textarea shows three example topics. No "Welcome" copy.
- **No slides yet**: stage-slides is unreachable until design completes.
  No empty-state-of-an-empty-state needed.

---

## 9. Terminal UI parity

The CLI mirrors the web UI flow exactly:

| Web UI stage  | CLI equivalent                                                        |
| ------------- | ---------------------------------------------------------------------- |
| stage-input   | Multi-line input ending with `.`                                       |
| stage-review  | Print critique + segments; `[a]approve [e]dit-in-$EDITOR [r]edraft`    |
| stage-slides  | List slide HTML paths; `[N]` opens slide N in `$EDITOR`, `[f N]` fixes |
| stage-record  | Print audio dir; `[n]` auto-narrate missing, `[a]` overwrite, `[f]inalize` |
| stage-final   | Print MP4 path; offer to `open` it                                     |

Design intent: a user who knows the web UI can pick up the CLI
immediately because the same nouns and verbs appear in the same order.

---

## 10. Accessibility

### Today (v0.1)

- **Contrast**: text-on-bg meets WCAG AA (15.4:1 for body text; pills
  ≥ 4.5:1 for status colours).
- **Keyboard**: every control is a real button/link/input; tab order
  follows visual order; no focus traps.
- **Semantic HTML**: `<header>`, `<main>`, `<section>` per stage,
  `<label>` for every input.
- **Iframe is sandboxed** with `allow-same-origin` only — the preview
  can't run scripts that interfere with the host UI.

### Known gaps

- **No screen-reader testing yet.** Stage transitions are visual-only
  (no ARIA live region announcing "now editing slides").
- **No high-contrast mode.** Dark theme only.
- **No font-size knob.** Relies on browser zoom.
- **No reduced-motion mode** (we don't have animations, so this is
  moot today, but worth being explicit if we add any).

These are tracked under accessibility-todo (not yet a filed issue).

---

## 11. Responsive design

### Desktop (≥ 900 px wide) — primary

- Single-column layout, 1100 px max content width.
- Slide-edit stage uses 2-column grid (`1fr / 280–600 px`) so the
  textarea has room to breathe.

### Tablet (600–900 px)

- Slide-edit stage stacks vertically (textarea on top, preview below).
- Preview wrap caps at 600 px so it doesn't dominate.

### Mobile (< 600 px) — best effort

- Same as tablet, but file-drop area is finger-friendly. The HTML
  editor is usable but not pleasant — we don't expect serious editing
  on mobile.
- Modal picker dropdowns are native (no custom select).

The CLI is the answer for users without a desktop browser.

---

## 12. Copy / voice

The product copy is plain, direct, and avoids hype.

| Don't                          | Do                                                            |
| ------------------------------ | ------------------------------------------------------------- |
| "Magical AI-powered scripts!"  | "Claude will write a narration, pick a slide aesthetic, and critique its own work (~30–60s)." |
| "Oops! Something went wrong"   | The actual exception message, including the backend name.     |
| "Generating amazing slides..." | "Designing 6 slides in parallel..."                            |
| "Click here to record!"        | "Record one audio file per slide (slide_00.wav, slide_01.wav, …)." |

The first-person plural ("we") never appears. The bot doesn't say
"I" or "we"; it just describes what it's doing.

---

## 13. Open design questions

| #   | Question                                                                                                | Resolves by |
| --- | ------------------------------------------------------------------------------------------------------- | ----------- |
| D1  | Should slide-tab labels truncate at 28 chars (current) or wrap?                                         | v0.2        |
| D2  | Should the live preview default to fit-to-width or 1:1, with a toggle for the other?                   | v0.2        |
| D3  | Should "Auto-narrate everything" require typing a confirmation word, not just a confirm() click?       | v0.2        |
| D4  | Should the script.txt download include the raw HTML for each slide too, for offline review?            | v0.3        |
| D5  | On the final video stage, should we offer per-slide re-record-and-rebuild without going back to record? | v1.0        |

---

## 14. Appendix

### A. The reference video as a design influence

The example video used as the quality bar is 3Blue1Brown's [*But what
is a neural network?*](https://www.youtube.com/watch?v=jx6FevmKJGg).
The design takes three things from it:

- **Restraint**: dark navy slides, one focal idea per slide, no
  decorative clutter. The slide-designer prompt enforces this.
- **Pacing**: ~160 wpm gives every analogy room to land. Used as the
  default for cue-video duration estimation.
- **Voice authorship**: the visible human authorship is what makes the
  video credible. The product never tries to hide that the slides
  were AI-generated, but the *voice* is the user's, and the script
  is the user-approved version.

### B. Why no Figma

This document IS the design artifact. The product is small enough that
ASCII wireframes are faster to maintain than Figma frames, and they
live next to the code in the same repo so they don't fall out of sync.
If the product grows past ~10 screens, this trade-off flips.
