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
- [Starting and stopping the server](#starting-and-stopping-the-server)
- [Terminal UI](#terminal-ui)
- [One-shot end-to-end](#one-shot-end-to-end-no-clicks-no-recording)
- [Writing rough points](#writing-rough-points) — directives + worked backprop example
- [Files you get per job](#files-you-get-per-job)
- [Re-recording a single slide](#re-recording-a-single-slide)
- [Smoke test](#smoke-test)
- [Troubleshooting](#troubleshooting)
- [Text-to-speech engines (`TTS_ENGINE`)](#text-to-speech-engines-tts_engine)
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
`claude_cli` → `codex_cli` → `gemini_cli` → `ollama` → `llm` in that order.
Subscription CLIs first (free, no per-call cost if you already pay for
Claude / ChatGPT / Google AI), then local Ollama (free but needs the
daemon running), then the paid-API catch-all via `llm`.

### Backend 1 — `claude_cli` (Claude Code subscription, no API key)

Already installed Claude Code? You're done. The bot detects the `claude`
binary and uses your subscription. Verify with `claude --version`.

```bash
export BACKEND=claude_cli   # optional; auto-detected anyway
```

### Backend 2 — `codex_cli` (OpenAI ChatGPT Plus / Pro subscription)

Uses [OpenAI's `codex` CLI](https://github.com/openai/codex) — same
authentication as your ChatGPT subscription, no separate API key.

```bash
npm install -g @openai/codex      # or: brew install codex (if available)
codex login                       # browser flow against your ChatGPT account
codex --version                   # sanity check

export BACKEND=codex_cli          # optional; auto-detected if `codex` is on PATH
# If your codex version uses a different non-interactive form, override:
# export CODEX_CMD="codex exec"   # the default — change only if your CLI differs
```

Costs nothing extra beyond your existing ChatGPT subscription. Quality
matches whatever model your `codex` CLI is configured to use (GPT-4.1,
GPT-5, o-series, etc.).

### Backend 3 — `gemini_cli` (Google AI Pro / free tier)

Uses [Google's `gemini` CLI](https://github.com/google-gemini/gemini-cli) —
authenticate against your Google account or set `GEMINI_API_KEY`. Google
AI's free tier is generous (millions of tokens / day for personal use).

```bash
npm install -g @google/gemini-cli
gemini auth                       # browser flow against your Google account
                                  # OR: export GEMINI_API_KEY=...
gemini --version

export BACKEND=gemini_cli         # optional; auto-detected if `gemini` is on PATH
# Override the non-interactive form if your version uses a different flag:
# export GEMINI_CMD="gemini -p"   # the default
```

Costs nothing on the free tier for casual use. Paid Google AI Pro
removes rate limits and unlocks larger context windows.

### Backend 4 — `ollama` (free, local, no internet)

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

### Backend 5 — `llm` (cloud API key — Anthropic / OpenAI / Gemini / …)

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
**and TTS engine** on a per-request basis. The badge shows the current
server defaults; the picker overrides them.

- **Backend** + **Model** ride along on `/script`, `/design`, and
  `/slide/{i}/fix`.
- **TTS** rides along on `/jobs/{id}/auto-narrate` only — it has no
  effect when you record your own audio.

So you can, for example, generate slides with Claude (the default LLM)
and have them narrated by Piper without restarting the server: just
pick `piper` from the TTS dropdown before clicking "Auto-narrate".

### Starting and stopping the server

**Web server only (auto-detect backend):**

```bash
cd content
.venv/bin/uvicorn app:app --reload --port 8000
```

**Pin the backend at startup:**

```bash
# Subscription (Claude Code)
BACKEND=claude_cli .venv/bin/uvicorn app:app --port 8000

# Local (Ollama) — make sure Ollama is running first (see below)
BACKEND=ollama OLLAMA_MODEL=llama3.2 \
    .venv/bin/uvicorn app:app --port 8000

# Cloud API key (any provider known to `llm`)
BACKEND=llm LLM_MODEL=claude-sonnet-4-5 \
    .venv/bin/uvicorn app:app --port 8000
```

**Stop the web server:**

```bash
lsof -ti :8000 | xargs kill         # graceful (SIGTERM)
lsof -ti :8000 | xargs kill -9      # force (if it hangs)
```

**Ollama daemon — only needed if you use `BACKEND=ollama`:**

```bash
brew services start ollama       # one-time; auto-starts on login afterwards
brew services restart ollama     # after upgrading Ollama
brew services stop  ollama       # session-only stop
brew services info  ollama       # current status

ollama serve                     # alternative: run in foreground (don't combine with brew services)
```

**Full shutdown (web server + Ollama):**

```bash
lsof -ti :8000 | xargs kill 2>/dev/null
brew services stop ollama
```

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

## Writing rough points

The "rough points" you paste are the *single* input the bot has — the
writer, the aesthetic-picker, the slide-designer, and the critic all
read the same text. So anything you put in there shapes the output.

### Minimal shape

A topic line, then 3–6 bullets:

```
What is recursion?
- a function that calls itself
- needs a base case
- the matryoshka / Russian-doll analogy
- factorial example
.
```

That's it. The final `.` on its own line is only needed when piping
via `cli.py --auto-narrate`; in the web UI you just click the button.

### Even shorter — input can be as little as 4 words

You don't even need bullets. A bare topic phrase works — the writer
fills in everything from its prompt's defaults (1st-year CS undergrad
audience, 3Blue1Brown style, curious tone). Try this:

```
vedic maths for square root
.
```

Four words. The bot will: pick its own slide aesthetic, decide on
~4–6 segments covering the technique, write narration, and design
slides. Useful when you want to *see* what the bot would do before
spending effort on directives.

The tradeoff: with less input you get less control over the angle
and analogies the writer chooses. For polished videos, bullets +
directives are worth the extra typing.

### Optional directives (recommended for serious videos)

You can put a labelled header *before* your rough points to control
tone, audience, voice, aesthetic, etc. The bot honours these because
the prompts pass the full text through. Use them sparingly — too many
directives crowd out the actual content.

| Directive          | What it influences                                                  | Example                                                  |
| ------------------ | -------------------------------------------------------------------- | -------------------------------------------------------- |
| `AUDIENCE`         | Reading level + assumed background (writer + critic)                | "a 2nd-year CS undergrad who knows Python but no calculus" |
| `TONE`             | Playfulness vs gravitas (writer)                                    | "playful but rigorous"                                   |
| `PERSONA`          | Who the narrator pretends to be (writer)                            | "a friendly grad-student TA who's slightly nerdy"        |
| `HUMOUR`           | How and how much (writer)                                           | "occasional dry asides, never forced"                    |
| `LANGUAGE`         | Output language + register                                          | "English; one or two physics analogies"                  |
| `STYLE`            | Reference creator or genre (writer + designer)                      | "3Blue1Brown — restrained, animated when it matters"     |
| `COLOR THEME`      | Slide palette (aesthetic-picker overrides default)                  | "dark navy #0e1a2b, soft white text, blue-teal accents"  |
| `SIMPLICITY`       | Where to define jargon vs assume it (writer)                        | "undergrad-friendly; define each new term once"          |

### Full worked example — backpropagation

This input uses every directive above. It's deliberately verbose to
*show* the format — most real videos won't need all 8 facets set.

```
TOPIC: How backpropagation actually trains a neural network

AUDIENCE: a curious 2nd-year CS undergrad who knows Python and basic
  calculus, but hasn't used the chain rule in 6 months
TONE: playful but rigorous; the math is real, but we never hide
  behind it
PERSONA: a friendly grad-student TA who's slightly nerdy and gets
  visibly excited when an idea lands
HUMOUR: Samay Raina style — deadpan, dry, occasional self-aware jab
  at math itself ("Mathematicians named this thing in the worst
  possible way"). Never forced; if it's not funny, just say the
  thing. No laugh-tracks, no exclamation marks.
LANGUAGE: English; one mechanical-engineering analogy, one cooking
  analogy if it fits
STYLE: 3Blue1Brown — restrained, animated when it matters, never
  busy. One focal idea per slide.
COLOR THEME: dark navy background (#0e1a2b), soft white text,
  blue-teal #4dd0e1 for the network diagram, soft yellow #ffd54f
  to highlight the active edge during backprop
SIMPLICITY: undergrad-friendly. Assume they can READ a derivative
  but not DERIVE one quickly. Define jargon the first time it
  appears. Avoid `nabla`, prefer the word "gradient".

ROUGH POINTS:
- the problem: a neural network has thousands to billions of "knobs"
  (weights and biases); how do we tune them all?
- naïve idea: try every knob in turn → impossible, even on a small
  network
- gradient descent: nudge each knob in the direction that reduces
  error a tiny bit. But how do we know which direction "down" is?
- we need the gradient — and the hard part is: how does THIS knob,
  buried 50 layers deep, affect the FINAL loss?
- the chain rule of calculus, applied like an assembly line in
  reverse: compute the output forward, walk backwards layer by
  layer, multiply local gradients along the way
- analogy: the network is a Rube Goldberg machine; backprop is
  asking each component "if I tweaked YOU, how much would the final
  ball-drop position move?"
- the punchline: ONE forward pass to compute the output, ONE
  backward pass to compute every gradient simultaneously — both are
  O(N), not O(N²)
- this is why deep learning works at all — without backprop,
  training even a tiny network would be impractical and the whole
  field would still be in the 1980s
.
```

### Same example, in Hindi/Hinglish

Same topic, same 8 bullets — but in the register a Hindi-speaking
Indian undergrad would actually find natural (Hindi base with English
technical terms left in place). The only directive that really changes
is `LANGUAGE`; everything else stays — the writer + critic prompts
are language-agnostic.

```
TOPIC: Neural network में backpropagation actually कैसे काम करता है?

AUDIENCE: एक 2nd-year CS undergrad (Indian college में) — Python आता
  है, basic calculus भी, लेकिन chain rule को 6 महीने हो गए
TONE: friendly और थोड़ा informal — जैसे senior whiteboard पर समझा रहा
  हो; math को छिपाना नहीं है, लेकिन डराना भी नहीं है
PERSONA: एक helpful senior या TA जो थोड़ा nerdy है और किसी idea पर
  excited हो जाता है
HUMOUR: occasional dry asides ("Mathematicians ने इसका worst possible
  नाम रखा है"), forced नहीं
LANGUAGE: Hindi with English technical terms (Hinglish). Technical
  शब्द जैसे "gradient", "loss", "weight", "layer" English ही रहेंगे —
  वो textbook में वैसे ही हैं, translate करने से confusion बढ़ेगा।
  Output: Devanagari script में Hindi + Roman script में English terms.
STYLE: 3Blue1Brown — restrained, animated when it matters, never busy.
  एक slide पर एक focal idea।
COLOR THEME: dark navy background (#0e1a2b), soft white text, blue-teal
  #4dd0e1 for the network diagram, soft yellow #ffd54f to highlight the
  active edge during backprop
SIMPLICITY: undergrad-friendly. मान लेना कि derivative READ करना आता है
  but DERIVE quickly नहीं कर सकते। Jargon को पहली बार आते ही define
  करना। `∇` या "nabla" use मत करना — सीधे "gradient" शब्द काफ़ी है।

ROUGH POINTS:
- problem यह है: एक neural network में हज़ारों से लेकर अरबों "knobs"
  होते हैं (weights और biases) — इन सबको एक साथ tune कैसे करें?
- naïve idea: हर knob को एक-एक करके try करें → impossible है, छोटे
  network में भी
- gradient descent का असली idea: हर knob को थोड़ा सा उस direction में
  सरकाओ जो error कम करे। But "नीचे" किधर है, यह कैसे पता चले?
- gradient चाहिए — और hard part यह है: एक knob जो 50 layers deep है,
  वो FINAL loss को कितना affect करता है?
- answer: chain rule of calculus, उल्टी direction में लगाओ — output
  forward compute करो, फिर layer-by-layer पीछे चलते हुए local
  gradients को multiply करते जाओ। यही "backward pass" है।
- analogy: network एक Rube Goldberg machine की तरह है — backprop हर
  component से पूछता है "अगर मैं तुझे थोड़ा tweak करूँ, तो final
  ball-drop position कितनी move होगी?"
- punchline: एक forward pass output निकालने के लिए, एक backward pass
  सारे gradients एक साथ निकाल देता है — दोनों O(N), O(N²) नहीं।
- यही reason है deep learning actually काम क्यों करता है — backprop
  के बिना एक छोटा network train करना भी impractical होता, और पूरा
  field अभी भी 1980s में अटका होता।
.
```

A few tips when writing rough points in Hindi (or any other language):

- **Keep technical terms in English** if your audience reads CS in
  English textbooks. "Backpropagation" in Devanagari (बैकप्रोपेगेशन)
  looks scholarly but a working CS student is more likely to know the
  English word.
- **Be explicit in the `LANGUAGE` directive** about which script(s)
  the output should use. Without it, the writer often hedges and
  produces awkward transliteration.
- **The critic prompt still scores on understandability, analogies,
  and wonder** — those land in any language. If a Hindi script comes
  back stilted, it usually means the analogies didn't translate; the
  fix is to provide better analogies in your rough points, not to
  tweak the prompt.

### What actually happens to each directive

The prompts pass your entire input through, so:

- `AUDIENCE`, `TONE`, `PERSONA`, `HUMOUR`, `SIMPLICITY` → influence
  the **writer** (`WRITER_PROMPT`) and the **critic**
  (`CRITIC_PROMPT`) — they show up as the voice and pitch of the
  narration.
- `LANGUAGE` → shapes word choice and which analogies the writer
  reaches for.
- `STYLE` and `COLOR THEME` → influence the **aesthetic-picker**
  (`AESTHETIC_PICKER_PROMPT`) and downstream the
  **slide-designer** (`SLIDE_DESIGNER_PROMPT`).

These are **strong suggestions, not hard guarantees** — the writer
might soften a tone that conflicts with the topic, or the
aesthetic-picker might tweak a colour for legibility at 1920×1080.
Use the in-app **"Ask bot to fix this slide"** panel to push back if
a specific slide drifts.

### Tips for getting consistently good output

1. **Start with the misconception or hook**, not the dictionary
   definition. The reviewer scores "wonder" — surprise beats
   completeness.
2. **Include at least one analogy** in your bullets. If you give
   the writer good ones, it uses yours; if you don't, it invents
   them and they're hit-or-miss.
3. **3–6 bullets is the sweet spot.** Fewer → bot has to invent
   more. More → bot starts skipping or padding.
4. **Skip jargon you'd have to define** — unless you set
   `SIMPLICITY` to assume the audience knows it.
5. **Bullets in the order you'd build understanding**, not the
   order of a textbook chapter. The writer respects your sequence.
6. **The directives are optional.** If you skip them all, the bot
   defaults to: 3Blue1Brown style, 1st-year CS undergrad audience,
   curious-and-restrained tone, dark navy aesthetic. That default
   is fine for most explainer-bot uses.

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

## Text-to-speech engines (`TTS_ENGINE`)

When you use **auto-narrate** (the "Auto-narrate missing slides" button,
or `cli.py --auto-narrate`), the bot picks a TTS engine via the
`TTS_ENGINE` env var. Three options:

| `TTS_ENGINE=`    | Voice quality        | Setup                          | License            |
| ---------------- | -------------------- | ------------------------------ | ------------------ |
| `say` (default)  | Decent (macOS built-in) | None — already there        | Proprietary, free  |
| **`piper`**      | Very good — neural   | pipx install + 1 voice file    | **Open source**    |
| **`supertonic`** | **Very good** — neural | pip install; auto-downloads models on first use | **Open source** ✨ |
| `espeak`         | Robotic but clear    | `brew install espeak-ng`       | Open source        |

### Piper (open-source, recommended)

[Piper](https://github.com/rhasspy/piper) is a small, fast, open-source
neural TTS that runs on CPU and produces **dramatically better** audio
than macOS `say` for explainer videos. Setup is a one-time install plus
a voice download.

**1. Install Piper:**

```bash
# pipx is the cleanest (isolated, on PATH globally)
brew install pipx 2>/dev/null     # if you don't already have it
pipx install piper-tts

# Alternatives if you prefer:
# uv tool install piper-tts
# .venv/bin/pip install piper-tts   # inside this project's venv
```

**2. Download a voice** (one .onnx file + its .onnx.json):

```bash
mkdir -p ~/piper-voices
cd ~/piper-voices
curl -L -O https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx
curl -L -O https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx.json
```

The "lessac medium" voice is ~30 MB and a good American English starter.
Browse <https://huggingface.co/rhasspy/piper-voices> for dozens of others
(other languages, male / female, smaller "low" or larger "high" sizes).

**3. Verify:**

```bash
echo "Hello from Piper." | piper -m ~/piper-voices/en_US-lessac-medium.onnx -f /tmp/test.wav
open /tmp/test.wav
```

**4. Use it for auto-narration:**

```bash
export TTS_ENGINE=piper
# Optional — if unset, the bot uses the first .onnx in ~/piper-voices/
export PIPER_VOICE=~/piper-voices/en_US-lessac-medium.onnx

# Now any auto-narrate flow uses Piper.
echo "your rough points ." | \
  BACKEND=ollama TTS_ENGINE=piper .venv/bin/python cli.py --auto-narrate
```

The pipeline writes `slide_NN.wav` (instead of `.aiff` with `say`); the
finalize step accepts either, so nothing else changes.

### Supertonic (open-source, on-device, auto-setup)

[Supertonic](https://github.com/supertone-inc/supertonic) is another
open-source neural TTS — and arguably easier to set up than Piper
because the pip package **auto-downloads its ONNX models** on first use
(~260 MB cached in your Hugging Face cache). No manual voice-file
download, no separate CLI install. Quality is generally on par with or
better than Piper, with a different set of preset voices.

**1. Install the package** (one of):

```bash
.venv/bin/uv add supertonic           # adds to this project's venv
# or:
pipx install supertonic               # isolated, global
# or:
.venv/bin/pip install supertonic      # any venv
```

The first time `_synthesize_supertonic` runs, it'll fetch the ONNX
models from <https://huggingface.co/Supertone/supertonic-3>. After
that, audio synthesis is fully offline.

**2. Pick a voice** (optional — defaults to `M4`):

```bash
export TTS_ENGINE=supertonic
export SUPERTONIC_VOICE=M4            # preset voice name; M1..M4, F1, F2, ...
export SUPERTONIC_LANG=en             # language code; "en", "ko", or "na" (language-agnostic)
```

See the [Supertonic model card](https://huggingface.co/Supertone/supertonic-3)
for the full voice list and language codes.

**3. Use it:**

```bash
# CLI one-shot
echo "your rough points ." | \
  BACKEND=ollama TTS_ENGINE=supertonic .venv/bin/python cli.py --auto-narrate

# Or the web server, with auto-narrate set to Supertonic by default
TTS_ENGINE=supertonic .venv/bin/uvicorn app:app --port 8000
```

In the web UI, the TTS dropdown lists `supertonic` directly — no
restart needed if the package is already installed.

### eSpeak-NG (fallback)

If you're not on macOS and don't want to install Piper, eSpeak-NG is
the lightest possible option:

```bash
brew install espeak-ng    # macOS
# apt-get install espeak-ng    (Linux)

export TTS_ENGINE=espeak
```

The voice is markedly robotic — useful as a sanity-check fallback, not
for a polished video.

### Switching engines

Set the env var when starting the server (or use the CLI):

```bash
TTS_ENGINE=piper .venv/bin/uvicorn app:app --port 8000
```

The web UI's "Auto-narrate" buttons inherit whatever engine the server
was started with. To change engines later, restart the server.

## Cost / quota

Each video uses roughly:

- 1 writer call (~2 k output tokens)
- 1 aesthetic-picker call (~200 tokens)
- 1 critic call (~500 tokens)
- N slide-design calls (~1 k tokens each), one per segment

Where those calls hit, and what they cost, depends on the backend:

- **`claude_cli`** — counts against your Claude Code subscription
  allowance, no extra billing.
- **`codex_cli`** — counts against your ChatGPT Plus / Pro / Team
  subscription, no extra billing.
- **`gemini_cli`** — counts against your Google AI Pro subscription,
  or the generous Google AI free tier if you're not on Pro.
- **`ollama`** — runs locally, no charge, no internet.
- **`llm`** — billed by the upstream provider (Anthropic / OpenAI /
  Gemini / …) at their token pricing. ~$0.02–$0.05 per video on
  Claude Sonnet at current prices; Gemini's free tier covers casual
  use.
