# Explainer Bot — User Guide

A friendly walkthrough for anyone who wants to make a short explainer
video without writing code, editing video, or learning new software.

> Looking for the technical reference (commands, environment variables,
> backend choice)? That lives in **[USER_MANUAL.md](USER_MANUAL.md)**.
> Looking for the project overview? That's the
> **[README](README.md)**. *This* file is for when someone else has
> already set up the bot for you and you just want to **use** it.

---

## Contents

- [What this is](#what-this-is)
- [Before you start](#before-you-start)
- [The whole journey in 7 steps](#the-whole-journey-in-7-steps)
- [Step 1 — Type your topic](#step-1--type-your-topic)
- [Step 2 — Read what the bot wrote](#step-2--read-what-the-bot-wrote)
- [Step 3 — Approve, and let the bot design the slides](#step-3--approve-and-let-the-bot-design-the-slides)
- [Step 4 — Look through the slides](#step-4--look-through-the-slides)
- [Step 5 — Build the cue video](#step-5--build-the-cue-video)
- [Step 6 — Voice the slides](#step-6--voice-the-slides)
- [Step 7 — Build the final video](#step-7--build-the-final-video)
- [Tips for getting good results](#tips-for-getting-good-results)
- [When something goes wrong](#when-something-goes-wrong)
- [FAQ](#faq)

---

## What this is

You give the bot a few rough ideas about a concept you want to
explain. The bot:

1. Writes a short script,
2. Checks its own work against three quality bars (is it understandable,
   does it use good analogies, does it convey wonder?),
3. Designs slides for each part of the script,
4. Lets you fix anything that doesn't look right,
5. Stitches the slides into a video,
6. Adds either **your recorded voice** or a **bot voice** as the
   narration,
7. Hands you a finished MP4 you can play, download, or share.

It's inspired by [3Blue1Brown](https://www.youtube.com/watch?v=jx6FevmKJGg)'s
style of clear, visually simple explainers.

A normal video takes **15–25 minutes** of your time end-to-end. Most
of that is reading the bot's script, deciding it's good, and (if you
choose) recording your voice.

---

## Before you start

You need:

- **A web browser** (Chrome, Safari, Firefox, Edge — any modern one).
- **A computer where someone has set up the bot for you.** This guide
  assumes the address `http://localhost:8000` (or similar) is already
  running. If it isn't, ask your technical helper to start the server
  — they'll know what that means.
- **(Optional) A microphone** if you want *your own voice* on the
  video. Any laptop's built-in mic works. The Voice Memos app on
  your phone also works.
- **(Optional) Headphones**, so you can hear the cue video play while
  you record.

That's it. No accounts, no payments, no software to install on your
side.

### What it's *not* for

- Long videos. The sweet spot is 1–3 minutes.
- Cinematic productions. The slides are clean and minimal, on purpose.
- Topics you don't actually understand. The bot writes a draft, but
  you decide whether it's right. Garbage in, polite garbage out.

---

## The whole journey in 7 steps

A bird's-eye view of what you'll do:

```
   1.  Open the page → type a few rough points → click "Draft script"
        ↓
   2.  The bot shows you a draft script. You read it. You edit it.
        ↓
   3.  You click "Approve" → the bot designs the slides
        ↓
   4.  You flip through the slides like a slideshow. Anything
       look wrong? Click "Ask bot to fix this slide" and describe
       the problem in words.
        ↓
   5.  You click "Build cue video" → the bot makes a silent slideshow
        ↓
   6.  Either:
            (a) record yourself reading the script, slide by slide, or
            (b) click "Auto-narrate" and let the bot voice it
        ↓
   7.  You click "Build final video" → out comes your MP4.
```

Each step has its own page in the bot's window; you go forward by
clicking a button and you can always scroll back up to check the
earlier step.

---

## Step 1 — Type your topic

Open the page (someone has shared an address like
`http://localhost:8000` with you). You'll see a big text box at the
top of the page labelled **"Rough points"**.

Type what you want to explain. The simplest possible input is **just a
short phrase**:

```
vedic maths for square root
```

That's four words and the bot will figure out the rest.

You'll usually get better results if you give it a bit more — a topic
line and a few bullet points capturing what *you* think is interesting
about the idea:

```
What is recursion?
- a function that calls itself
- needs a base case or it never stops
- the matryoshka / Russian-doll analogy
- factorial example
```

A few rules of thumb:

- **3 to 6 bullets is the sweet spot.** Fewer makes the bot guess
  more; more makes it skim.
- **Start with the surprising bit**, not the textbook definition.
  Surprise lands better than completeness.
- **Bring your own analogies.** If you give the bot a good analogy
  ("Russian dolls", "wind tunnel", "passport stamps"), it'll use it.
  If you don't, it'll invent one — and the invented ones are
  hit-or-miss.
- **Skip jargon** you wouldn't bother defining out loud.

When you're happy, click the blue **"Draft script"** button. The bot
takes about 30–60 seconds. The button greys out while it thinks;
that's normal.

> **Advanced:** if you have strong feelings about tone, audience,
> humour, colour theme, etc., you can write a labelled header before
> your bullets. The full menu of these options lives in
> [USER_MANUAL.md → Writing rough points](USER_MANUAL.md#writing-rough-points).
> You don't *need* any of them for a first video.

---

## Step 2 — Read what the bot wrote

After it thinks, the page changes. You'll see three panels:

### The aesthetic the bot chose

A small block at the top says something like *"Aesthetic — Chalkboard
Recursion"* with a few colour swatches and a sentence about the look
it picked for your slides. This is mostly informational — the bot
decides this from your topic.

### The reviewer's critique

A panel that looks like this:

```
Reviewer critique     [approve]
   understandability: 5/5    analogies: 4/5    wonder: 5/5

   • Consider clarifying the base case in segment 2.
```

The reviewer is a second AI that read the bot's draft and scored it
on three things:

1. **Understandability** — would a first-year CS student follow every
   sentence on first listen?
2. **Analogies** — does the script use good analogies (and not
   misleading ones)?
3. **Wonder** — does the script make the idea feel surprising and
   beautiful, instead of textbook-boring?

A green **approve** badge means the reviewer signed off. A yellow
**revise** badge means it suggests changes — you can still proceed,
but check the notes first.

### The script itself

Below the critique, the script appears as a list of slide segments.
Each one has three editable fields:

- **Title** — what'll appear at the top of the slide.
- **Visual** — a one-line description of what the slide should
  show. Used by the slide-designer, not shown on the slide itself.
- **Narration** — what the voice (yours or the bot's) will say.

You can **edit any of these directly in the box**. Click into any
field, change the words, and your change is saved automatically.

> **You're in charge here.** The bot drafted, but you're the editor.
> If a sentence feels stilted, fix it. If a segment is in the wrong
> order, copy its title/visual/narration to where you want it (or
> just re-draft from new rough points).

---

## Step 3 — Approve, and let the bot design the slides

When the script reads well to you, click the blue
**"Approve script → design slides"** button at the bottom.

The bot now takes the *narration* you approved and writes HTML for
one slide per segment. This takes another 30–60 seconds. There's a
small grey hint "Designing slides… 30–60 s" so you know it didn't
freeze.

What's happening behind the scenes: the bot writes one self-contained
HTML page per slide, 1920 by 1080 pixels (the standard video size).
It then takes a screenshot of each page — that screenshot is what
ends up in the final video.

You won't see anything happen on screen until it's done. The page
will switch to **Step 4** on its own.

---

## Step 4 — Look through the slides

Now the page shows:

- **A row of tabs at the top** — one tab per slide. "1. A function
  that calls itself", "2. The matryoshka picture", and so on.
- **A textbox on the left** — the HTML code for the current slide.
- **A live preview on the right** — what the slide looks like right
  now, at the same proportions it'll appear in the video. Updates as
  you type.

### Click through every tab

Spend 30 seconds clicking each tab and looking at the preview. You're
checking for:

- **Is anything overlapping?** Title smashed into a diagram, two
  labels touching each other, text running off the side.
- **Is the title readable?** Big, contrasty, not buried.
- **Does the visual support the narration?** A slide titled "the
  base case" should have something that looks like a base case.

The slides are *usually* fine. When they're not, you have two
choices.

### Option A — Ask the bot to fix it in words

Below the textbox you'll see a button **"Report issue / ask bot to
fix"**. Click it. A textarea opens. Write a sentence describing
what's wrong, in plain English:

> *The title overlaps the diagram on the left side.*

> *The bullet labels are too close together to read.*

> *The colour of the arrow makes it invisible on the dark background.*

Click **"Ask bot to fix this slide"**. The bot rewrites that slide
(20–40 s) and updates both the textbox and the preview. Look again.

You can ask it to fix the same slide as many times as you need. Each
fix builds on the previous one.

### Option B — Edit the HTML yourself

If you happen to know HTML/CSS, you can change the code on the left
directly. The preview updates as you type. Click **"Re-render this
slide"** to save your changes.

If you don't know HTML, **option A is for you**. You don't have to
learn anything; just describe the problem in words.

### When all slides look good

Scroll to the bottom and click **"Build cue video"**.

---

## Step 5 — Build the cue video

The bot now takes the screenshots of all the slides and stitches them
into a **silent video** — no narration yet. Each slide is shown for
roughly the time it would take to read its narration out loud. Think
of it as a guide track for the voice you're about to add.

This step takes about 10–30 seconds.

When it's ready you'll see:

- **A video player** showing the cue video.
- **Two download buttons** — one for the cue video, one for a text
  file called `script.txt`.

Press play on the cue video and watch it once. This is the visual
flow your viewers will see; the only thing missing is the voice.

### What's the script.txt for?

If you scroll down, you'll also see the script printed inline. It's
broken up per slide, with timestamps:

```
SLIDE 1/4   (0:00 → 0:15,  ~15.0s)
Filename:  slide_00.wav
Title:     A Function That Calls Itself
Visual:    A function box labeled f(n) with an arrow looping out…

Narration:
  Imagine you write a function, and somewhere inside its own code, it
  calls itself. That's recursion…

────────────────────────────────────────────────────────────────────
SLIDE 2/4  …
```

If you're going to record your own voice, **download this file** (or
read it off the screen). You'll read the "Narration" block for each
slide.

---

## Step 6 — Voice the slides

You have two choices.

### Choice A — Record yourself (best quality)

This is what gives a video that "human" feel — the same thing that
makes channels like 3Blue1Brown enjoyable to watch.

For each slide:

1. **Open a recorder.** Voice Memos on your phone is fine. QuickTime
   on a Mac (File → New Audio Recording) also works. So does any
   other recorder you have.
2. **Read the "Narration" block aloud** for that slide. Don't worry
   about exact timing — you control the pace.
3. **Save the file** with a specific name:
   - First slide → **`slide_00.wav`** (or `.mp3`, `.m4a`, `.aiff`…
     any common audio file works)
   - Second slide → **`slide_01.wav`**
   - Third slide → **`slide_02.wav`**
   - …and so on.

The filename matters. `slide_00`, not `slide_1` or `Slide_00`. The
number is **zero-padded** (always two digits) and the first slide is
**00**, not 01.

When you have all the files:

4. **Drag-and-drop them** onto the box that says "Drop audio files
   here, or click to choose." Or click the box and select them in
   the file picker.

The page updates and shows you a table of every slide and whether it
has audio yet:

```
   #   Slide title              Expected filename    Status
   1   A Function That Calls…   slide_00.<ext>       slide_00.wav — 12.3s
   2   The Matryoshka Picture   slide_01.<ext>       missing
   3   …                        slide_02.<ext>       slide_02.wav — 18.7s
```

Slides with audio get a green tag and their length. Missing ones
show a red **"missing"** tag.

**Re-recording a slide is easy** — just drop the new file with the
same name. The old one is replaced.

### Choice B — Let the bot voice it (fastest)

If you don't want to record (or you're just previewing the video
before committing), use the buttons under the upload box:

- **"Auto-narrate missing slides"** — fills in audio only for the
  slides you haven't recorded yet. Your own recordings stay
  untouched.
- **"Auto-narrate everything (overwrite)"** — replaces *all* slide
  audio with the bot's voice. Useful for a fresh preview. Warns you
  first because it deletes any of your recordings.

The bot voice is functional but robotic — fine for previews; less
warm than your own voice for a video you actually want people to
watch.

> **Picking a different bot voice.** If your operator has set up
> nicer voices (like Piper or Supertonic), the **TTS** dropdown at
> the very top of the page lets you choose one before clicking
> Auto-narrate. The default works fine if you don't touch it.

---

## Step 7 — Build the final video

When every slide has audio (green tags all the way down), the
**"Build final video"** button at the bottom turns blue and becomes
clickable. Click it.

The bot:

1. Reads the length of each audio file you supplied,
2. Makes a clip for each slide that lasts exactly that long,
3. Stitches all the clips into one MP4.

This takes about 10–30 seconds.

When it's done, the page shows:

- **A video player** with your finished video. Press play and watch it.
- A **"Download MP4"** button. Click it and the file lands in your
  Downloads folder.
- A **"Make another"** button. Resets the page so you can do another
  topic.

That's the whole flow. **You now have a publishable MP4.**

---

## Tips for getting good results

A few things that experienced users find make a noticeable difference:

### 1. Write the punchline into your rough points

The bot is best at *connecting* ideas, not at finding *which* idea is
worth landing. If you know what the "aha!" moment is, put it in your
bullets verbatim. The bot will preserve it.

### 2. Read the script aloud once before approving

Reading aloud catches awkward phrasing your eye skips over. If a
sentence trips your tongue, the recording will sound bad. Fix it
*before* clicking Approve.

### 3. Spend your edit time on slides 1, 2, and the last one

The first two slides set the hook; the last slide is what viewers
remember. The middle is mostly carried by your narration. If you
only have time to perfect a few slides, perfect those.

### 4. Record in one sitting if you can

Voice has a natural pitch and energy that varies day to day. If you
record slide 1 today and slide 5 tomorrow, the difference is
audible. A single session with a quiet room and a cup of water
sounds tighter.

### 5. Make a draft video with the bot's voice first

Run the whole pipeline with **"Auto-narrate everything"** before you
record anything. Watch it. *Then* decide which slides to re-record
in your own voice. Often you'll change a few words in the script
after hearing it back — easier to do that *before* you've recorded
the rest.

### 6. The bot's slide designer respects what you write

If your bullet says "three labelled circles in a row," the slide
will have three labelled circles in a row. Vague bullets ("a
diagram") produce vague slides. Specific bullets ("a function box
labeled f(n) with an arrow looping back to itself") produce
specific slides.

---

## When something goes wrong

Plain-English version of the most common hiccups.

### "The page is just spinning forever on Draft script"

The bot is waiting for the AI to reply. It can take up to a minute,
sometimes longer if the AI is busy. If it's been over **3 minutes**,
refresh the page and try again with a slightly shorter input.

### "It says the first slide is blank"

Click the second slide tab, then click back to the first. That
sometimes refreshes the preview. If it's still blank, click the
**"Revert to bot's version"** button.

### "The bot's voice is reading numbers weirdly"

Auto-narrate engines pronounce things differently. Try a different
voice from the **TTS** dropdown at the top of the page (if your
operator has set up alternatives). Or just record those slides
yourself — you say the numbers right, by definition.

### "My uploaded audio file isn't showing up"

The filename has to start with `slide_NN` where `NN` is the slide
number, **two digits**, starting from `slide_00`. Files like
`Slide 1.wav` or `recording.mp3` won't be recognised. Rename and
re-drop.

### "I want to start over"

Scroll to the very top of the page. The **"Rough points"** box is
always there. Edit the points, click **"Draft script"** again, and
the bot will create a fresh job. You'll get a confirmation prompt
first if you're in the middle of editing slides ("This will abandon
your current job") — say yes if you've decided to start fresh.

If you'd rather wipe everything, click **"Make another"** on the
final-video page.

### "The video has no audio"

Three things to check:

1. Is your computer's volume turned on?
2. Did all the slides have green tags before you clicked Build?
3. Are you opening the file in a player that supports MP4? (Try
   QuickTime, VLC, or just drop it on a web page.)

### "I want to fix one slide after I've already built the final video"

Easy. Scroll up to the slide-edit page. Use the **"Ask bot to fix
this slide"** button. Then re-build the cue video, re-upload (or
auto-narrate) only that one slide's audio, and re-build the final
video. Your other audio recordings will be reused — only the
re-recorded slide changes.

---

## FAQ

**Do I need an AI account?** No. Your operator set up the connection
to the AI when they installed the bot. You just use the web page.

**How long should my video be?** The bot is best at 1–3 minute
videos, which usually means 4–8 slides. Longer is possible but the
bot's writing strength is in tight, focused topics.

**Can I make videos in other languages?** Yes. Write your rough
points in the language you want, and add a line at the top like
`LANGUAGE: Hindi with English technical terms`. The bot writes in
that language. Voice-over depends on whether your operator has set
up a voice engine that speaks it — for your own voice, you can speak
any language.

**Can I share the video?** Yes. The MP4 you download is yours. Drop
it on YouTube, X, your blog, or wherever.

**What if the topic is private/confidential?** If your operator set
the bot up using a local AI (Ollama) or a local voice engine
(Piper / Supertonic), nothing leaves your computer. If they set it
up with a cloud service (Claude / GPT / Gemini), your rough points
and script *do* go to that service. Check with your operator if
you're unsure.

**Where do my files go?** On the computer where the bot is running,
under a folder called `jobs/<a-random-id>/`. Each video has its own
folder containing the slides, audio, script, and final MP4. Your
operator can show you where.

**Can I edit the script after building?** Not directly — but you can
edit the rough points, click "Draft script" again, and start a new
attempt. Old attempts are kept on disk so you don't lose them.

**Can I undo a slide-fix request?** Yes. Each slide has a **"Revert
to bot's version"** button that throws away your local edits or
fixes for that one slide.

---

## What to do if you get stuck

1. Refresh the page. Most things recover.
2. Check the [When something goes wrong](#when-something-goes-wrong)
   section above.
3. Ask your operator. They have access to the deeper troubleshooting
   in [USER_MANUAL.md](USER_MANUAL.md) and can usually fix things in
   a minute.
4. Try a smaller topic. If a 10-slide video isn't working, a
   3-slide one usually does.

That's the whole guide. Enjoy making videos.
