"""End-to-end pipeline: rough points -> cue video -> audio -> final video.

External dependencies (must be on PATH):
  - claude       (Claude Code CLI; uses your subscription, no API key)
  - ffmpeg / ffprobe
  - say          (macOS built-in TTS, used by auto-narrate only)
And the playwright python package + chromium browser.

The pipeline runs in two stages:

  Stage 1  ``build_cue``  : draft a script, design slides, render a SILENT
                            "cue" video where each slide is shown for the
                            estimated narration length. Produces a script.txt
                            telling the user exactly what to read into each
                            ``slide_NN.wav`` file.

  Stage 2  ``build_final`` : take the per-slide audio recordings and assemble
                             the final narrated video. Each slide's duration
                             is set to the duration of its audio file. Audio
                             can come from one of two sources, interchangeably:
                               * the user records and drops files into the
                                 ``jobs/<id>/audio/`` folder, OR
                               * ``auto_narrate`` synthesises them with macOS
                                 ``say`` for the slides that don't already
                                 have user-supplied audio.
"""
from __future__ import annotations

import asyncio
import json
import re
import shutil
import subprocess
import textwrap
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from playwright.async_api import async_playwright

from prompts import (
    AESTHETIC_PICKER_PROMPT,
    CRITIC_PROMPT,
    SLIDE_DESIGNER_PROMPT,
    WRITER_PROMPT,
)

ROOT = Path(__file__).resolve().parent
JOBS_DIR = ROOT / "jobs"
JOBS_DIR.mkdir(exist_ok=True)

VIDEO_W, VIDEO_H = 1920, 1080
CLAUDE_TIMEOUT_S = 240
SPEAKING_WPM = 160          # how fast we assume the user will read
MIN_SLIDE_SECONDS = 4.0     # minimum length for a single cue slide
SLIDE_TAIL_PAD_S = 1.0      # quiet padding at the end of each slide


# ---------------------------------------------------------------------------
# Claude CLI wrapper
# ---------------------------------------------------------------------------

async def claude(system_prompt: str, user_message: str) -> str:
    """Call the local `claude` CLI non-interactively. Returns raw stdout text."""
    proc = await asyncio.create_subprocess_exec(
        "claude",
        "-p",
        "--append-system-prompt",
        system_prompt,
        user_message,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=CLAUDE_TIMEOUT_S)
    except asyncio.TimeoutError:
        proc.kill()
        raise RuntimeError(f"claude CLI timed out after {CLAUDE_TIMEOUT_S}s")
    if proc.returncode != 0:
        raise RuntimeError(f"claude CLI failed: {stderr.decode(errors='replace')[:500]}")
    return stdout.decode(errors="replace").strip()


_FENCE_RE = re.compile(r"^```[a-zA-Z]*\s*|\s*```$", re.MULTILINE)


def _strip_fences(text: str) -> str:
    return _FENCE_RE.sub("", text).strip()


def _extract_json(text: str) -> Any:
    """Best-effort JSON extraction. Falls back to the first balanced block."""
    text = _strip_fences(text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    for opener, closer in (("[", "]"), ("{", "}")):
        start = text.find(opener)
        if start == -1:
            continue
        depth = 0
        for i in range(start, len(text)):
            if text[i] == opener:
                depth += 1
            elif text[i] == closer:
                depth -= 1
                if depth == 0:
                    return json.loads(text[start : i + 1])
    raise ValueError(f"Could not parse JSON from model output: {text[:300]}")


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class Segment:
    title: str
    key_visual: str
    narration: str


@dataclass
class Aesthetic:
    name: str
    palette: list[str]
    font_family: str
    description: str


@dataclass
class Critique:
    scores: dict[str, int]
    verdict: str               # "approve" | "revise"
    notes: list[str]


@dataclass
class ScriptDraft:
    topic: str
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
    progress: list[str] = field(default_factory=list)


@dataclass
class FinalResult:
    job_id: str
    final_video_path: Path
    progress: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Stage 1a: script writing + critique
# ---------------------------------------------------------------------------

async def draft_script(rough_points: str) -> ScriptDraft:
    """Generate segments, aesthetic, and a critique. Parallel where possible."""
    topic_line = rough_points.strip().splitlines()[0][:120] if rough_points.strip() else "Untitled"

    writer_user = f"Rough points from the user:\n\n{rough_points}\n\nProduce the JSON array now."
    aesthetic_user = f"Topic: {topic_line}\n\nFull rough points for context:\n{rough_points}"

    segments_raw, aesthetic_raw = await asyncio.gather(
        claude(WRITER_PROMPT, writer_user),
        claude(AESTHETIC_PICKER_PROMPT, aesthetic_user),
    )

    seg_list = _extract_json(segments_raw)
    segments = [
        Segment(title=s["title"], key_visual=s["key_visual"], narration=s["narration"])
        for s in seg_list
    ]
    aes = _extract_json(aesthetic_raw)
    aesthetic = Aesthetic(
        name=aes["name"],
        palette=list(aes["palette"]),
        font_family=aes["font_family"],
        description=aes["description"],
    )

    critic_user = "Script to review (JSON array of slide segments):\n\n" + json.dumps(
        [s.__dict__ for s in segments], indent=2
    )
    critique_raw = await claude(CRITIC_PROMPT, critic_user)
    crit = _extract_json(critique_raw)
    critique = Critique(
        scores=dict(crit["scores"]),
        verdict=str(crit["verdict"]),
        notes=list(crit["notes"]),
    )

    return ScriptDraft(topic=topic_line, segments=segments, critique=critique, aesthetic=aesthetic)


# ---------------------------------------------------------------------------
# Slide design + screenshot
# ---------------------------------------------------------------------------

def _aesthetic_brief(aesthetic: Aesthetic) -> str:
    return textwrap.dedent(
        f"""
        Aesthetic name: {aesthetic.name}
        Palette (first color is the background): {", ".join(aesthetic.palette)}
        Font family (CSS): {aesthetic.font_family}
        Description: {aesthetic.description}
        """
    ).strip()


async def _design_slide(topic: str, aesthetic: Aesthetic, segment: Segment) -> str:
    user = textwrap.dedent(
        f"""
        TOPIC: {topic}

        CHOSEN AESTHETIC:
        {_aesthetic_brief(aesthetic)}

        THIS SLIDE:
          title: {segment.title}
          key_visual: {segment.key_visual}

        Produce the HTML now.
        """
    ).strip()
    html = await claude(SLIDE_DESIGNER_PROMPT, user)
    return _strip_fences(html)


async def _screenshot_slide(html: str, out_png: Path, browser) -> None:
    page = await browser.new_page(viewport={"width": VIDEO_W, "height": VIDEO_H})
    try:
        await page.set_content(html, wait_until="networkidle")
        await page.screenshot(path=str(out_png), full_page=False, omit_background=False)
    finally:
        await page.close()


# ---------------------------------------------------------------------------
# Duration estimation + ffmpeg helpers
# ---------------------------------------------------------------------------

def _estimate_duration(narration: str, wpm: int = SPEAKING_WPM) -> float:
    """Estimate how many seconds it takes to read `narration` aloud."""
    words = max(1, len(narration.split()))
    seconds = words / (wpm / 60.0) + SLIDE_TAIL_PAD_S
    return max(MIN_SLIDE_SECONDS, round(seconds, 2))


def _probe_duration(path: Path) -> float:
    out = subprocess.check_output(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(path),
        ]
    )
    return float(out.decode().strip())


def _build_silent_clip(png: Path, duration: float, out_clip: Path) -> None:
    """One slide image -> silent video clip of the given duration."""
    subprocess.run(
        [
            "ffmpeg", "-y", "-loglevel", "error",
            "-loop", "1", "-t", f"{duration:.3f}", "-i", str(png),
            "-f", "lavfi", "-t", f"{duration:.3f}",
            "-i", "anullsrc=channel_layout=stereo:sample_rate=48000",
            "-c:v", "libx264", "-tune", "stillimage", "-pix_fmt", "yuv420p",
            "-vf", f"scale={VIDEO_W}:{VIDEO_H},fps=30",
            "-c:a", "aac", "-b:a", "128k",
            "-shortest", str(out_clip),
        ],
        check=True,
    )


def _build_voiced_clip(png: Path, audio: Path, duration: float, out_clip: Path) -> None:
    """One slide image + user audio -> a clip of length `duration`."""
    subprocess.run(
        [
            "ffmpeg", "-y", "-loglevel", "error",
            "-loop", "1", "-t", f"{duration:.3f}", "-i", str(png),
            "-i", str(audio),
            "-c:v", "libx264", "-tune", "stillimage", "-pix_fmt", "yuv420p",
            "-vf", f"scale={VIDEO_W}:{VIDEO_H},fps=30",
            "-c:a", "aac", "-b:a", "192k",
            "-shortest", str(out_clip),
        ],
        check=True,
    )


def _concat_clips(clips: list[Path], out_mp4: Path, work_dir: Path) -> None:
    concat_list = work_dir / "concat.txt"
    concat_list.write_text("".join(f"file '{c.resolve()}'\n" for c in clips))
    subprocess.run(
        [
            "ffmpeg", "-y", "-loglevel", "error",
            "-f", "concat", "-safe", "0", "-i", str(concat_list),
            "-c", "copy", str(out_mp4),
        ],
        check=True,
    )


def _fmt_ts(seconds: float) -> str:
    s = int(round(seconds))
    return f"{s // 60}:{s % 60:02d}"


def _render_script_text(
    topic: str,
    segments: list[Segment],
    durations: list[float],
    audio_dir_name: str,
) -> str:
    """Human-readable cue sheet the user reads while recording."""
    lines = [
        f"# {topic}",
        "",
        "Record each slide as a separate audio file (.wav, .mp3, .m4a, or .aiff)",
        f"and drop them into the `{audio_dir_name}/` folder using the filenames below.",
        "Each estimated time is just a hint — your actual recording length will set the",
        "slide duration in the final video.",
        "",
        "─" * 78,
        "",
    ]
    cursor = 0.0
    for i, (seg, dur) in enumerate(zip(segments, durations)):
        start = _fmt_ts(cursor)
        end = _fmt_ts(cursor + dur)
        cursor += dur
        lines.extend([
            f"SLIDE {i + 1}/{len(segments)}   ({start} → {end},  ~{dur:.1f}s)",
            f"Filename:  slide_{i:02d}.wav   (any common audio format is fine)",
            f"Title:     {seg.title}",
            f"Visual:    {seg.key_visual}",
            "",
            "Narration:",
        ])
        for paragraph in textwrap.wrap(seg.narration, width=76):
            lines.append("  " + paragraph)
        lines.extend(["", "─" * 78, ""])
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Stage 1b: cue (slides + silent cue video + script.txt)
# ---------------------------------------------------------------------------

def _job_dir(job_id: str) -> Path:
    return JOBS_DIR / job_id


def _save_plan(job_dir: Path, topic: str, aesthetic: Aesthetic, segments: list[Segment]) -> None:
    """Persist the plan so build_final can be called in a separate process."""
    plan = {
        "topic": topic,
        "aesthetic": asdict(aesthetic),
        "segments": [asdict(s) for s in segments],
    }
    (job_dir / "plan.json").write_text(json.dumps(plan, indent=2))


def _load_plan(job_dir: Path) -> tuple[str, Aesthetic, list[Segment]]:
    data = json.loads((job_dir / "plan.json").read_text())
    aes = Aesthetic(**data["aesthetic"])
    segs = [Segment(**s) for s in data["segments"]]
    return data["topic"], aes, segs


def _slide_html_path(job_dir: Path, index: int) -> Path:
    return job_dir / "slides" / f"slide_{index:02d}.html"


def _slide_png_path(job_dir: Path, index: int) -> Path:
    return job_dir / "slides" / f"slide_{index:02d}.png"


@dataclass
class DesignResult:
    """Output of stage `design_slides` — HTML for every slide, no screenshots yet."""
    job_id: str
    slide_html_paths: list[Path]
    progress: list[str] = field(default_factory=list)


async def design_slides(
    topic: str,
    aesthetic: Aesthetic,
    segments: list[Segment],
    job_id: str | None = None,
    progress_cb=None,
) -> DesignResult:
    """Generate slide HTML (no screenshots, no cue video). Persists plan.json
    and one .html file per slide so they can be edited before rendering."""
    job_id = job_id or uuid.uuid4().hex[:10]
    job_dir = _job_dir(job_id)
    if job_dir.exists():
        shutil.rmtree(job_dir)
    slides_dir = job_dir / "slides"
    audio_dir = job_dir / "audio"
    work_dir = job_dir / "work"
    for d in (slides_dir, audio_dir, work_dir):
        d.mkdir(parents=True)

    progress: list[str] = []

    def log(msg: str) -> None:
        progress.append(msg)
        if progress_cb:
            try:
                progress_cb(msg)
            except Exception:
                pass

    _save_plan(job_dir, topic, aesthetic, segments)

    log(f"Designing {len(segments)} slides in parallel...")
    htmls = await asyncio.gather(
        *(_design_slide(topic, aesthetic, seg) for seg in segments)
    )

    paths: list[Path] = []
    for i, html in enumerate(htmls):
        p = _slide_html_path(job_dir, i)
        p.write_text(html)
        paths.append(p)
        log(f"Wrote slide {i + 1}/{len(htmls)} HTML ({len(html)} bytes)")

    return DesignResult(job_id=job_id, slide_html_paths=paths, progress=progress)


def get_slide_html(job_id: str, index: int) -> str:
    p = _slide_html_path(_job_dir(job_id), index)
    if not p.exists():
        raise FileNotFoundError(f"no HTML for slide {index} in job {job_id}")
    return p.read_text()


def update_slide_html(job_id: str, index: int, html: str) -> Path:
    """Replace the HTML for one slide. Caller should re-screenshot afterward."""
    job_dir = _job_dir(job_id)
    if not (job_dir / "plan.json").exists():
        raise FileNotFoundError(f"no plan for job {job_id}")
    _, _, segments = _load_plan(job_dir)
    if not 0 <= index < len(segments):
        raise IndexError(f"slide index {index} out of range (0..{len(segments) - 1})")
    p = _slide_html_path(job_dir, index)
    p.write_text(html)
    return p


async def screenshot_slides(
    job_id: str,
    indices: list[int] | None = None,
    progress_cb=None,
) -> list[Path]:
    """Render the specified slides' HTML to PNG. Defaults to all slides."""
    job_dir = _job_dir(job_id)
    if not (job_dir / "plan.json").exists():
        raise FileNotFoundError(f"no plan for job {job_id}")
    _, _, segments = _load_plan(job_dir)
    if indices is None:
        indices = list(range(len(segments)))

    pngs: list[Path] = []
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        try:
            for i in indices:
                html_path = _slide_html_path(job_dir, i)
                if not html_path.exists():
                    raise FileNotFoundError(f"missing HTML for slide {i}: {html_path}")
                png = _slide_png_path(job_dir, i)
                await _screenshot_slide(html_path.read_text(), png, browser)
                pngs.append(png)
                if progress_cb:
                    progress_cb(f"Captured slide {i + 1}/{len(segments)}")
        finally:
            await browser.close()
    return pngs


async def assemble_cue_video(
    job_id: str,
    progress_cb=None,
) -> CueResult:
    """Assumes slide PNGs already exist. Builds silent cue video + script.txt."""
    job_dir = _job_dir(job_id)
    if not (job_dir / "plan.json").exists():
        raise FileNotFoundError(f"no plan for job {job_id}")
    topic, _aesthetic, segments = _load_plan(job_dir)
    work_dir = job_dir / "work"
    work_dir.mkdir(exist_ok=True)
    audio_dir = job_dir / "audio"
    audio_dir.mkdir(exist_ok=True)

    progress: list[str] = []

    def log(msg: str) -> None:
        progress.append(msg)
        if progress_cb:
            try:
                progress_cb(msg)
            except Exception:
                pass

    slide_pngs: list[Path] = []
    for i in range(len(segments)):
        png = _slide_png_path(job_dir, i)
        if not png.exists():
            raise FileNotFoundError(
                f"missing slide PNG for slide {i}: {png} — call screenshot_slides first"
            )
        slide_pngs.append(png)

    durations = [_estimate_duration(s.narration) for s in segments]

    log("Building silent cue video...")
    clips: list[Path] = []
    for i, (png, dur) in enumerate(zip(slide_pngs, durations)):
        clip = work_dir / f"cue_clip_{i:02d}.mp4"
        _build_silent_clip(png, dur, clip)
        clips.append(clip)
    cue_mp4 = job_dir / "cue_video.mp4"
    _concat_clips(clips, cue_mp4, work_dir)

    script_text = _render_script_text(topic, segments, durations, audio_dir.name)
    script_path = job_dir / "script.txt"
    script_path.write_text(script_text)

    log("Cue ready.")
    return CueResult(
        job_id=job_id,
        cue_video_path=cue_mp4,
        script_text_path=script_path,
        slide_pngs=slide_pngs,
        estimated_durations=durations,
        audio_dir=audio_dir,
        progress=progress,
    )


async def build_cue(
    topic: str,
    aesthetic: Aesthetic,
    segments: list[Segment],
    job_id: str | None = None,
    progress_cb=None,
) -> CueResult:
    """Convenience all-in-one: design → screenshot → assemble. Equivalent to
    `design_slides` + `screenshot_slides` + `assemble_cue_video`."""
    design = await design_slides(topic, aesthetic, segments, job_id=job_id,
                                 progress_cb=progress_cb)
    if progress_cb:
        progress_cb("Launching headless browser for screenshots...")
    await screenshot_slides(design.job_id, progress_cb=progress_cb)
    cue = await assemble_cue_video(design.job_id, progress_cb=progress_cb)
    # Preserve the design-stage progress lines for callers that read .progress.
    cue.progress = design.progress + cue.progress
    return cue


# ---------------------------------------------------------------------------
# Stage 2: finalize with user-recorded audio
# ---------------------------------------------------------------------------

_AUDIO_EXTS = (".wav", ".mp3", ".m4a", ".aac", ".aiff", ".aif", ".flac", ".ogg", ".opus")
SAY_VOICE = "Samantha"
SAY_RATE_WPM = 175


def find_audio_for_slide(audio_dir: Path, index: int) -> Path | None:
    """Look for slide_{index:02d}.{ext} in `audio_dir`."""
    stem = f"slide_{index:02d}"
    for p in sorted(audio_dir.iterdir()):
        if p.is_file() and p.stem == stem and p.suffix.lower() in _AUDIO_EXTS:
            return p
    return None


def auto_narrate(
    job_id: str,
    overwrite: bool = False,
    progress_cb=None,
) -> list[Path]:
    """Generate audio for the job with macOS ``say``.

    Writes one ``slide_NN.aiff`` per segment into ``jobs/<id>/audio/``.

    By default we skip any slide that already has user-provided audio, so
    a user can hand-record a few slides and let the bot fill the rest.
    Set ``overwrite=True`` to replace every slide's audio (the user's
    recordings are deleted in that case).
    """
    job_dir = _job_dir(job_id)
    if not (job_dir / "plan.json").exists():
        raise FileNotFoundError(f"no plan for job {job_id}")
    _, _, segments = _load_plan(job_dir)
    audio_dir = job_dir / "audio"
    audio_dir.mkdir(exist_ok=True)

    written: list[Path] = []
    for i, seg in enumerate(segments):
        existing = find_audio_for_slide(audio_dir, i)
        if existing is not None and not overwrite:
            if progress_cb:
                progress_cb(f"slide {i + 1}: keeping existing {existing.name}")
            continue
        if existing is not None and overwrite:
            existing.unlink()
        out = audio_dir / f"slide_{i:02d}.aiff"
        subprocess.run(
            ["say", "-v", SAY_VOICE, "-r", str(SAY_RATE_WPM),
             "-o", str(out), seg.narration],
            check=True,
        )
        written.append(out)
        if progress_cb:
            progress_cb(f"slide {i + 1}: synthesised {out.name}")
    return written


def audio_status(job_id: str) -> dict[str, Any]:
    """Report which slides have audio and which don't, for the UI."""
    job_dir = _job_dir(job_id)
    if not (job_dir / "plan.json").exists():
        raise FileNotFoundError(f"no plan for job {job_id}")
    _, _, segments = _load_plan(job_dir)
    audio_dir = job_dir / "audio"
    audio_dir.mkdir(exist_ok=True)
    slides = []
    for i, seg in enumerate(segments):
        path = find_audio_for_slide(audio_dir, i)
        slides.append({
            "index": i,
            "title": seg.title,
            "expected_filename_stem": f"slide_{i:02d}",
            "have_audio": path is not None,
            "audio_filename": path.name if path else None,
            "audio_duration_s": _probe_duration(path) if path else None,
        })
    return {
        "job_id": job_id,
        "audio_dir": str(audio_dir),
        "slides": slides,
        "all_present": all(s["have_audio"] for s in slides),
    }


async def build_final(job_id: str, progress_cb=None) -> FinalResult:
    job_dir = _job_dir(job_id)
    slides_dir = job_dir / "slides"
    audio_dir = job_dir / "audio"
    work_dir = job_dir / "work"
    if not slides_dir.exists():
        raise FileNotFoundError(f"missing slides/ for job {job_id} — run build_cue first")
    if not (job_dir / "plan.json").exists():
        raise FileNotFoundError(f"missing plan.json for job {job_id}")

    _, _, segments = _load_plan(job_dir)

    progress: list[str] = []

    def log(msg: str) -> None:
        progress.append(msg)
        if progress_cb:
            try:
                progress_cb(msg)
            except Exception:
                pass

    audio_paths: list[Path] = []
    for i in range(len(segments)):
        p = find_audio_for_slide(audio_dir, i)
        if p is None:
            raise FileNotFoundError(
                f"missing audio file for slide {i + 1}: expected slide_{i:02d}.<audio-ext> "
                f"in {audio_dir}"
            )
        audio_paths.append(p)

    log("Building per-slide clips with your audio...")
    clips: list[Path] = []
    for i, (audio, seg) in enumerate(zip(audio_paths, segments)):
        png = slides_dir / f"slide_{i:02d}.png"
        if not png.exists():
            raise FileNotFoundError(f"missing slide image: {png}")
        dur = _probe_duration(audio)
        clip = work_dir / f"final_clip_{i:02d}.mp4"
        _build_voiced_clip(png, audio, dur, clip)
        clips.append(clip)
        log(f"  slide {i + 1}/{len(segments)} — {dur:.1f}s")

    out_mp4 = job_dir / "video.mp4"
    log("Concatenating final video...")
    _concat_clips(clips, out_mp4, work_dir)
    log("Done.")

    return FinalResult(job_id=job_id, final_video_path=out_mp4, progress=progress)
