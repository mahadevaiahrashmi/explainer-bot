"""Interactive terminal UI with the same features as the web UI.

Flow:
  1. Type or paste rough points (end with a line containing only `.`, or pipe via stdin).
  2. See script + critique. Approve or open each segment in $EDITOR.
  3. Cue video + script.txt are generated.
  4. Drop your audio files into the printed path, hit enter; pipeline assembles
     the final video.

Usage:
    .venv/bin/python cli.py                 # interactive
    .venv/bin/python cli.py --resume <id>   # skip ahead to the audio stage of an existing job
"""
from __future__ import annotations

import argparse
import asyncio
import os
import subprocess
import sys
import textwrap
from pathlib import Path

from pipeline import (
    JOBS_DIR,
    Segment,
    assemble_cue_video,
    audio_status,
    auto_narrate,
    build_final,
    design_slides,
    draft_script,
    fix_slide,
    screenshot_slides,
)


# ----- colours (no deps) ---------------------------------------------------

class C:
    if sys.stdout.isatty():
        DIM = "\033[2m"; BOLD = "\033[1m"; RESET = "\033[0m"
        FG_CYAN = "\033[36m"; FG_GREEN = "\033[32m"; FG_YELLOW = "\033[33m"
        FG_RED = "\033[31m"; FG_BLUE = "\033[34m"; FG_MAGENTA = "\033[35m"
    else:
        DIM = BOLD = RESET = ""
        FG_CYAN = FG_GREEN = FG_YELLOW = FG_RED = FG_BLUE = FG_MAGENTA = ""


def hr(label: str = "") -> None:
    width = 78
    if label:
        bar = "─" * max(0, width - len(label) - 4)
        print(f"\n{C.DIM}── {label} {bar}{C.RESET}")
    else:
        print(C.DIM + "─" * width + C.RESET)


def info(msg: str) -> None:    print(f"{C.FG_CYAN}{msg}{C.RESET}")
def good(msg: str) -> None:    print(f"{C.FG_GREEN}{msg}{C.RESET}")
def warn(msg: str) -> None:    print(f"{C.FG_YELLOW}{msg}{C.RESET}")
def err(msg: str) -> None:     print(f"{C.FG_RED}{msg}{C.RESET}")


def read_rough_points() -> str:
    """Read multi-line input from the user. End with a line containing just `.`"""
    if not sys.stdin.isatty():
        return sys.stdin.read()
    print(f"{C.BOLD}Type your rough points.{C.RESET} "
          f"{C.DIM}End with a single dot (.) on its own line.{C.RESET}\n")
    lines: list[str] = []
    while True:
        try:
            line = input()
        except EOFError:
            break
        if line.strip() == ".":
            break
        lines.append(line)
    return "\n".join(lines)


def edit_in_editor(initial: str, suffix: str = ".md") -> str:
    """Open $EDITOR (or vi) on `initial` text, return edited content."""
    import tempfile
    editor = os.environ.get("EDITOR") or os.environ.get("VISUAL") or "vi"
    with tempfile.NamedTemporaryFile("w+", suffix=suffix, delete=False) as f:
        f.write(initial)
        path = f.name
    try:
        subprocess.run([editor, path], check=False)
        return Path(path).read_text()
    finally:
        try: os.unlink(path)
        except OSError: pass


def render_critique(critique) -> None:
    verdict_colour = C.FG_GREEN if critique.verdict == "approve" else C.FG_YELLOW
    print(f"  Verdict: {verdict_colour}{critique.verdict}{C.RESET}")
    scores_str = "  ".join(f"{k}: {C.BOLD}{v}/5{C.RESET}" for k, v in critique.scores.items())
    print(f"  Scores:  {scores_str}")
    if critique.notes:
        print(f"\n  {C.DIM}Reviewer notes:{C.RESET}")
        for n in critique.notes:
            wrapped = textwrap.fill(n, width=74, initial_indent="    • ", subsequent_indent="      ")
            print(wrapped)


def render_segments(segments: list[Segment]) -> None:
    for i, s in enumerate(segments):
        print(f"\n  {C.BOLD}{i + 1}. {s.title}{C.RESET}")
        print(f"     {C.DIM}visual:{C.RESET} {textwrap.shorten(s.key_visual, 110)}")
        print(f"     {C.DIM}narration:{C.RESET} {textwrap.shorten(s.narration, 110)}")


def edit_segments(segments: list[Segment]) -> list[Segment]:
    """Dump segments to a temp Markdown file the user can edit."""
    doc_lines = ["# Edit the script below. Save and close when done.\n"]
    for i, s in enumerate(segments):
        doc_lines.extend([
            f"\n## Slide {i + 1}",
            f"\n### title",
            s.title,
            f"\n### key_visual",
            s.key_visual,
            f"\n### narration",
            s.narration,
            "",
        ])
    edited = edit_in_editor("\n".join(doc_lines), suffix=".md")
    return _parse_segments_md(edited, fallback=segments)


def _parse_segments_md(text: str, fallback: list[Segment]) -> list[Segment]:
    """Very forgiving parser for the format produced by edit_segments()."""
    chunks = text.split("\n## Slide")
    out: list[Segment] = []
    for chunk in chunks[1:]:           # skip header
        fields = {"title": "", "key_visual": "", "narration": ""}
        current: str | None = None
        buf: list[str] = []
        for raw in chunk.splitlines():
            stripped = raw.strip()
            low = stripped.lower()
            if low.startswith("### title"):
                if current: fields[current] = "\n".join(buf).strip()
                current, buf = "title", []
            elif low.startswith("### key_visual"):
                if current: fields[current] = "\n".join(buf).strip()
                current, buf = "key_visual", []
            elif low.startswith("### narration"):
                if current: fields[current] = "\n".join(buf).strip()
                current, buf = "narration", []
            elif current:
                buf.append(raw)
        if current:
            fields[current] = "\n".join(buf).strip()
        if any(fields.values()):
            out.append(Segment(**fields))
    if not out:
        warn("Could not parse edited script; keeping previous version.")
        return fallback
    return out


def ask(prompt: str, default: str = "y") -> str:
    suffix = " [Y/n]: " if default.lower() == "y" else " [y/N]: "
    try:
        ans = input(f"{C.BOLD}{prompt}{C.RESET}{suffix}").strip().lower()
    except EOFError:
        return default.lower()
    return ans or default.lower()


def progress_printer(msg: str) -> None:
    print(f"  {C.DIM}· {msg}{C.RESET}")


# ----- main flow -----------------------------------------------------------

async def run_first_time() -> str:
    """Returns the job_id after the cue stage completes."""
    hr("rough points")
    rough = read_rough_points().strip()
    if not rough:
        err("Empty input — nothing to do."); sys.exit(1)

    hr("drafting script + critique  (~30–60s)")
    draft = await draft_script(rough)
    info(f"Topic: {C.BOLD}{draft.topic}{C.RESET}")
    info(f"Aesthetic: {draft.aesthetic.name}  "
         f"{C.DIM}({', '.join(draft.aesthetic.palette)}){C.RESET}")

    hr("critique")
    render_critique(draft.critique)
    hr("segments")
    render_segments(draft.segments)

    while True:
        choice = input(
            f"\n{C.BOLD}[a]{C.RESET}pprove   "
            f"{C.BOLD}[e]{C.RESET}dit in $EDITOR   "
            f"{C.BOLD}[r]{C.RESET}edraft (new rough points)   "
            f"{C.BOLD}[q]{C.RESET}uit: "
        ).strip().lower()
        if choice in ("a", ""):
            break
        if choice == "e":
            draft.segments = edit_segments(draft.segments)
            hr("segments")
            render_segments(draft.segments)
            continue
        if choice == "r":
            return await run_first_time()
        if choice == "q":
            sys.exit(0)

    hr(f"designing {len(draft.segments)} slides (HTML only — no screenshots yet)")
    design = await design_slides(draft.topic, draft.aesthetic, draft.segments,
                                 progress_cb=progress_printer)
    good(f"\nSlide HTML written under: {design.slide_html_paths[0].parent}")

    edit_slides_loop(design.job_id, design.slide_html_paths)

    hr(f"screenshotting slides + building cue video")
    await screenshot_slides(design.job_id, progress_cb=progress_printer)
    cue = await assemble_cue_video(design.job_id, progress_cb=progress_printer)
    good("\nCue ready.")
    print(f"  Cue video : {cue.cue_video_path}")
    print(f"  Script    : {cue.script_text_path}")
    print(f"  Audio dir : {cue.audio_dir}")
    return cue.job_id


def edit_slides_loop(job_id: str, html_paths: list[Path]) -> None:
    """Let the user edit any slide HTML in $EDITOR (or have the bot fix it)
    before screenshots are taken.

    NOTE: Not async; the user is sitting in front of the prompt, no concurrency.
    """
    while True:
        hr("slide HTML")
        for i, p in enumerate(html_paths):
            size = p.stat().st_size if p.exists() else 0
            print(f"  {i + 1}. {p}  {C.DIM}({size} bytes){C.RESET}")
        try:
            choice = input(
                f"\n{C.BOLD}[1..{len(html_paths)}]{C.RESET} edit slide in $EDITOR   "
                f"{C.BOLD}[f N]{C.RESET} ask bot to fix slide N   "
                f"{C.BOLD}[o]{C.RESET}pen slides folder   "
                f"{C.BOLD}[d]{C.RESET}one (build cue video)   "
                f"{C.BOLD}[q]{C.RESET}uit: "
            ).strip().lower()
        except EOFError:
            return  # non-interactive: skip edits, proceed
        if choice in ("d", ""):
            return
        if choice == "q":
            sys.exit(0)
        if choice == "o":
            subprocess.run(["open", str(html_paths[0].parent)])
            continue
        if choice.startswith("f"):
            rest = choice[1:].strip()
            if not rest.isdigit():
                warn("Usage: f <slide number>, e.g. `f 2`")
                continue
            idx = int(rest) - 1
            if not 0 <= idx < len(html_paths):
                warn(f"Slide number must be between 1 and {len(html_paths)}.")
                continue
            print(f"\nDescribe the issue with slide {idx + 1} in plain English.")
            print(f"{C.DIM}Examples: 'title overlaps the diagram', 'text runs off the right edge',")
            print(f"          'second label unreadable on dark bg'. End with a single dot (.) on its own line.{C.RESET}")
            buf: list[str] = []
            while True:
                try:
                    ln = input()
                except EOFError:
                    break
                if ln.strip() == ".":
                    break
                buf.append(ln)
            issue = "\n".join(buf).strip()
            if not issue:
                warn("Empty issue — skipping.")
                continue
            hr(f"asking bot to fix slide {idx + 1}")
            try:
                asyncio.run(_fix_and_rerender(job_id, idx, issue))
                good(f"Slide {idx + 1} fixed and re-rendered.")
            except Exception as e:
                err(f"Fix failed: {e}")
            continue
        if choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(html_paths):
                editor = os.environ.get("EDITOR") or os.environ.get("VISUAL") or "vi"
                subprocess.run([editor, str(html_paths[idx])])
                continue
        warn("Not a valid choice.")


async def _fix_and_rerender(job_id: str, index: int, issue: str) -> None:
    """Helper: call fix_slide then screenshot that slide."""
    await fix_slide(job_id, index, issue)
    await screenshot_slides(job_id, indices=[index],
                            progress_cb=progress_printer)


def wait_for_audio_loop(job_id: str) -> None:
    """Show audio status; let user upload more / continue when ready."""
    while True:
        st = audio_status(job_id)
        hr(f"audio status — job {job_id}")
        for s in st["slides"]:
            mark = (f"{C.FG_GREEN}✓{C.RESET}" if s["have_audio"] else f"{C.FG_RED}·{C.RESET}")
            fname = s["audio_filename"] or f"slide_{s['index']:02d}.<ext>"
            dur = f"  ({s['audio_duration_s']:.1f}s)" if s["audio_duration_s"] else ""
            print(f"  {mark} slide {s['index'] + 1}: {fname}{dur}  "
                  f"{C.DIM}— {s['title']}{C.RESET}")
        if st["all_present"]:
            good(f"\nAll {len(st['slides'])} audio files present.")
            choice = input(
                f"{C.BOLD}[f]{C.RESET}inalize   "
                f"{C.BOLD}[o]{C.RESET}pen audio folder   "
                f"{C.BOLD}[a]{C.RESET}uto-narrate all (overwrite)   "
                f"{C.BOLD}[r]{C.RESET}escan   "
                f"{C.BOLD}[q]{C.RESET}uit: "
            ).strip().lower()
        else:
            print(f"\n{C.DIM}Drop files into:{C.RESET} {st['audio_dir']}")
            print(f"{C.DIM}Each file must start with `slide_NN` "
                  f"(e.g. slide_00.wav, slide_01.m4a).{C.RESET}")
            choice = input(
                f"{C.BOLD}[n]{C.RESET}arrate missing with `say`   "
                f"{C.BOLD}[a]{C.RESET}uto-narrate all (overwrite)   "
                f"{C.BOLD}[o]{C.RESET}pen audio folder   "
                f"{C.BOLD}[r]{C.RESET}escan   "
                f"{C.BOLD}[q]{C.RESET}uit: "
            ).strip().lower()
        if choice == "o":
            subprocess.run(["open", st["audio_dir"]])
        elif choice == "q":
            sys.exit(0)
        elif choice == "f" and st["all_present"]:
            return
        elif choice == "n":
            hr("auto-narrating missing slides")
            auto_narrate(job_id, overwrite=False, progress_cb=progress_printer)
        elif choice == "a":
            if ask("This replaces every slide's audio. Continue?", default="n").startswith("y"):
                hr("auto-narrating all slides")
                auto_narrate(job_id, overwrite=True, progress_cb=progress_printer)
        # any other key (or 'r') -> rescan


async def run_finalize(job_id: str) -> None:
    hr("building final video")
    final = await build_final(job_id, progress_cb=progress_printer)
    good(f"\nFinal video: {final.final_video_path}")
    if sys.stdout.isatty():
        if ask("Open it now?", default="y").startswith("y"):
            subprocess.run(["open", str(final.final_video_path)])


async def amain() -> None:
    ap = argparse.ArgumentParser(description="Explainer Bot — terminal UI")
    ap.add_argument("--resume", metavar="JOB_ID",
                    help="Skip drafting; go straight to audio status for an existing job")
    ap.add_argument("--auto-narrate", action="store_true",
                    help="Skip the audio-recording wait; auto-narrate any missing slides "
                         "with macOS `say` and finalize immediately.")
    args = ap.parse_args()

    if args.resume:
        job_dir = JOBS_DIR / args.resume
        if not (job_dir / "plan.json").exists():
            err(f"No such job: {args.resume} (looked in {job_dir})"); sys.exit(1)
        job_id = args.resume
        info(f"Resuming job {job_id}")
    else:
        job_id = await run_first_time()

    if args.auto_narrate:
        hr("auto-narrating missing slides")
        auto_narrate(job_id, overwrite=False, progress_cb=progress_printer)
    else:
        wait_for_audio_loop(job_id)

    await run_finalize(job_id)


if __name__ == "__main__":
    try:
        asyncio.run(amain())
    except KeyboardInterrupt:
        print()
        sys.exit(130)
