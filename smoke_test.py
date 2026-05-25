"""Smoke test the two-stage pipeline end-to-end.

We use macOS `say` only as a stand-in for "the user recorded their voice"
so the test runs unattended. The pipeline itself doesn't call `say`.

Usage: cd content && .venv/bin/python smoke_test.py
"""
import asyncio
import subprocess
import sys

from pipeline import audio_status, build_cue, build_final, draft_script


async def main() -> None:
    rough = (
        "What is recursion?\n"
        "- a function that calls itself\n"
        "- needs a base case or it never stops\n"
        "- the russian-doll / matryoshka analogy\n"
        "- a brief example: factorial"
    )

    print("[1/4] Drafting script + critique...")
    draft = await draft_script(rough)
    print(f"  topic: {draft.topic}")
    print(f"  aesthetic: {draft.aesthetic.name}")
    print(f"  critique: {draft.critique.verdict}  {draft.critique.scores}")
    print(f"  {len(draft.segments)} segments")

    # Trim for speed.
    draft.segments = draft.segments[:2]
    print(f"  [smoke] truncated to {len(draft.segments)} segments for speed")

    print("\n[2/4] Building cue video...")
    cue = await build_cue(draft.topic, draft.aesthetic, draft.segments,
                          progress_cb=lambda m: print(f"     · {m}"))
    print(f"  cue_video : {cue.cue_video_path}")
    print(f"  script    : {cue.script_text_path}")
    print(f"  audio_dir : {cue.audio_dir}")

    print(f"\n[3/4] Faking user-recorded audio with `say` "
          f"into {cue.audio_dir} ...")
    for i, seg in enumerate(draft.segments):
        out = cue.audio_dir / f"slide_{i:02d}.aiff"
        subprocess.run(
            ["say", "-v", "Samantha", "-r", "175", "-o", str(out), seg.narration],
            check=True,
        )
        print(f"     · wrote {out.name}")

    st = audio_status(cue.job_id)
    assert st["all_present"], "expected all audio files present"

    print("\n[4/4] Building final video...")
    final = await build_final(cue.job_id, progress_cb=lambda m: print(f"     · {m}"))
    size = final.final_video_path.stat().st_size
    print(f"\nDone: {final.final_video_path}  ({size} bytes)")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(130)
