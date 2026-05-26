"""FastAPI app: chat UI + script/cue/finalize endpoints."""
from __future__ import annotations

import asyncio
import shutil
import traceback
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse
from pydantic import BaseModel

from pipeline import (
    Aesthetic,
    JOBS_DIR,
    Segment,
    VALID_BACKENDS,
    assemble_cue_video,
    audio_status,
    auto_narrate,
    build_cue,
    build_final,
    current_backend_info,
    design_slides,
    draft_script,
    find_audio_for_slide,
    fix_slide,
    get_slide_html,
    screenshot_slides,
    set_request_overrides,
    update_slide_html,
)

ROOT = Path(__file__).resolve().parent
TEMPLATES = ROOT / "templates"

app = FastAPI(title="Explainer Bot")

JOBS: dict[str, dict[str, Any]] = {}   # in-process job state


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class ScriptRequest(BaseModel):
    rough_points: str
    backend: str | None = None        # one of pipeline.VALID_BACKENDS, or None for default
    model: str | None = None          # passed to ollama / llm backends; ignored for claude_cli


class SegmentIn(BaseModel):
    title: str
    key_visual: str
    narration: str


class AestheticIn(BaseModel):
    name: str
    palette: list[str]
    font_family: str
    description: str


class CueRequest(BaseModel):
    topic: str
    aesthetic: AestheticIn
    segments: list[SegmentIn]
    backend: str | None = None
    model: str | None = None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def index() -> str:
    return (TEMPLATES / "chat.html").read_text()


@app.get("/backend")
async def get_backend_info() -> dict[str, Any]:
    """Tell the UI what backend is the current server-side default, plus the
    list of valid backends. The UI uses this to populate the picker."""
    try:
        info = current_backend_info()
    except Exception as e:
        info = {"backend": None, "model": None, "source": "error", "error": str(e)}
    return {**info, "valid_backends": list(VALID_BACKENDS)}


@app.post("/script")
async def post_script(req: ScriptRequest) -> dict[str, Any]:
    if not req.rough_points.strip():
        raise HTTPException(400, "rough_points cannot be empty")
    try:
        set_request_overrides(req.backend, req.model)
        draft = await draft_script(req.rough_points)
    except RuntimeError as e:
        # Bad backend name → 400, not 500.
        if "Unknown backend" in str(e):
            raise HTTPException(400, str(e))
        traceback.print_exc()
        raise HTTPException(500, f"script generation failed: {e}")
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(500, f"script generation failed: {e}")
    return {
        "topic": draft.topic,
        "aesthetic": asdict(draft.aesthetic),
        "segments": [asdict(s) for s in draft.segments],
        "critique": asdict(draft.critique),
    }


@app.post("/design")
async def post_design(req: CueRequest) -> dict[str, Any]:
    """Generate slide HTML for every segment (no screenshots, no cue video).
    Synchronous — usually <30s — the user is waiting on this to edit slides."""
    job_id = uuid.uuid4().hex[:10]
    JOBS[job_id] = {
        "stage": "design",
        "status": "running",
        "progress": [],
        "error": None,
        "cue_video": None,
        "script": None,
        "final_video": None,
    }
    try:
        set_request_overrides(req.backend, req.model)
        aesthetic = Aesthetic(**req.aesthetic.model_dump())
        segments = [Segment(**s.model_dump()) for s in req.segments]
        result = await design_slides(
            req.topic, aesthetic, segments, job_id=job_id,
            progress_cb=lambda m: JOBS[job_id]["progress"].append(m),
        )
        # Persist the picks so /render-cue & /slide-fix calls for this job
        # inherit them without the UI having to re-send.
        JOBS[job_id]["backend"] = req.backend
        JOBS[job_id]["model"] = req.model
        JOBS[job_id]["status"] = "done"
        return {
            "job_id": result.job_id,
            "slides": [
                {
                    "index": i,
                    "title": s.title,
                    "html": p.read_text(),
                }
                for i, (s, p) in enumerate(zip(segments, result.slide_html_paths))
            ],
        }
    except RuntimeError as e:
        if "Unknown backend" in str(e):
            JOBS[job_id]["status"] = "error"
            raise HTTPException(400, str(e))
        traceback.print_exc()
        JOBS[job_id]["status"] = "error"
        JOBS[job_id]["error"] = str(e)
        raise HTTPException(500, f"design failed: {e}")
    except Exception as e:
        traceback.print_exc()
        JOBS[job_id]["status"] = "error"
        JOBS[job_id]["error"] = str(e)
        raise HTTPException(500, f"design failed: {e}")


@app.get("/jobs/{job_id}/slide/{index}/html", response_class=PlainTextResponse)
async def get_slide_html_endpoint(job_id: str, index: int) -> str:
    try:
        return get_slide_html(job_id, index)
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))


class HtmlBody(BaseModel):
    html: str
    rerender: bool = True   # also re-screenshot after saving


@app.put("/jobs/{job_id}/slide/{index}/html")
async def put_slide_html(job_id: str, index: int, body: HtmlBody) -> dict[str, Any]:
    try:
        update_slide_html(job_id, index, body.html)
    except (FileNotFoundError, IndexError) as e:
        raise HTTPException(404, str(e))
    if body.rerender:
        try:
            await screenshot_slides(job_id, indices=[index])
        except Exception as e:
            traceback.print_exc()
            raise HTTPException(500, f"re-screenshot failed: {e}")
    return {"saved": True, "rerendered": body.rerender}


@app.get("/jobs/{job_id}/slide/{index}/png")
async def get_slide_png(job_id: str, index: int) -> FileResponse:
    p = JOBS_DIR / job_id / "slides" / f"slide_{index:02d}.png"
    if not p.exists():
        raise HTTPException(404, "slide PNG not found — call PUT html first")
    # ?t= cache-buster handled by the client.
    return FileResponse(p, media_type="image/png")


class FixBody(BaseModel):
    issue: str
    rerender: bool = True
    backend: str | None = None
    model: str | None = None


@app.post("/jobs/{job_id}/slide/{index}/fix")
async def post_slide_fix(job_id: str, index: int, body: FixBody) -> dict[str, Any]:
    """Ask the LLM to fix a reported issue with this slide.

    Body: { issue: "title overlaps the diagram", rerender: true }
    Returns the new HTML so the editor can refresh.
    """
    if not body.issue.strip():
        raise HTTPException(400, "issue cannot be empty")
    j = JOBS.get(job_id, {})
    # Picker on this request beats job-stored picks beats server default.
    set_request_overrides(
        body.backend or j.get("backend"),
        body.model or j.get("model"),
    )
    try:
        new_html = await fix_slide(job_id, index, body.issue)
    except (FileNotFoundError, IndexError, ValueError) as e:
        raise HTTPException(400 if isinstance(e, (ValueError, IndexError)) else 404, str(e))
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(500, f"slide fix failed: {e}")
    if body.rerender:
        try:
            await screenshot_slides(job_id, indices=[index])
        except Exception as e:
            traceback.print_exc()
            raise HTTPException(500, f"re-screenshot after fix failed: {e}")
    return {"html": new_html, "rerendered": body.rerender}


@app.post("/jobs/{job_id}/render-cue")
async def post_render_cue(job_id: str) -> dict[str, str]:
    """Re-screenshot all slides and rebuild the silent cue video.
    Use this after PUT'ing slide HTML edits. Async — poll status."""
    if job_id not in JOBS:
        # Allow rendering for design jobs not yet in the dict (e.g. after restart).
        JOBS[job_id] = {"stage": "design", "status": "done", "progress": [],
                        "error": None, "cue_video": None, "script": None,
                        "final_video": None}
    j = JOBS[job_id]
    j["stage"] = "cue"
    j["status"] = "queued"
    j["progress"] = []
    j["error"] = None
    j["cue_video"] = None

    async def run() -> None:
        j["status"] = "running"

        def log(msg: str) -> None:
            j["progress"].append(msg)

        try:
            await screenshot_slides(job_id, progress_cb=log)
            result = await assemble_cue_video(job_id, progress_cb=log)
            j["cue_video"] = str(result.cue_video_path)
            j["script"] = str(result.script_text_path)
            j["audio_dir"] = str(result.audio_dir)
            j["status"] = "done"
        except Exception as e:
            traceback.print_exc()
            j["status"] = "error"
            j["error"] = str(e)

    asyncio.create_task(run())
    return {"job_id": job_id}


@app.post("/cue")
async def post_cue(req: CueRequest) -> dict[str, str]:
    """Legacy all-in-one: design + screenshot + assemble. Prefer /design then
    /render-cue if you want to edit HTML between the two."""
    job_id = uuid.uuid4().hex[:10]
    JOBS[job_id] = {
        "stage": "cue",
        "status": "queued",
        "progress": [],
        "error": None,
        "cue_video": None,
        "script": None,
        "final_video": None,
    }

    async def run() -> None:
        JOBS[job_id]["status"] = "running"

        def log(msg: str) -> None:
            JOBS[job_id]["progress"].append(msg)

        try:
            set_request_overrides(req.backend, req.model)
            aesthetic = Aesthetic(**req.aesthetic.model_dump())
            segments = [Segment(**s.model_dump()) for s in req.segments]
            result = await build_cue(
                req.topic, aesthetic, segments, job_id=job_id, progress_cb=log
            )
            JOBS[job_id]["cue_video"] = str(result.cue_video_path)
            JOBS[job_id]["script"] = str(result.script_text_path)
            JOBS[job_id]["audio_dir"] = str(result.audio_dir)
            JOBS[job_id]["status"] = "done"
        except Exception as e:
            traceback.print_exc()
            JOBS[job_id]["status"] = "error"
            JOBS[job_id]["error"] = str(e)

    asyncio.create_task(run())
    return {"job_id": job_id}


@app.get("/jobs/{job_id}/status")
async def get_status(job_id: str) -> dict[str, Any]:
    if job_id not in JOBS:
        raise HTTPException(404, "unknown job")
    j = JOBS[job_id]
    audio = None
    try:
        audio = audio_status(job_id)
    except FileNotFoundError:
        audio = None
    return {
        "stage": j["stage"],
        "status": j["status"],
        "progress": j["progress"],
        "error": j["error"],
        "has_cue_video": bool(j.get("cue_video")),
        "has_final_video": bool(j.get("final_video")),
        "audio": audio,
    }


@app.get("/jobs/{job_id}/cue")
async def get_cue(job_id: str) -> FileResponse:
    if job_id not in JOBS or not JOBS[job_id].get("cue_video"):
        raise HTTPException(404, "cue video not ready")
    return FileResponse(JOBS[job_id]["cue_video"], media_type="video/mp4",
                        filename=f"{job_id}-cue.mp4")


@app.get("/jobs/{job_id}/script")
async def get_script(job_id: str) -> PlainTextResponse:
    if job_id not in JOBS or not JOBS[job_id].get("script"):
        raise HTTPException(404, "script not ready")
    text = Path(JOBS[job_id]["script"]).read_text()
    return PlainTextResponse(text)


@app.post("/jobs/{job_id}/audio")
async def upload_audio(job_id: str, files: list[UploadFile] = File(...)) -> dict[str, Any]:
    """Upload one or more audio files. Each file's name must be slide_NN.<ext>."""
    if job_id not in JOBS:
        raise HTTPException(404, "unknown job")
    audio_dir = JOBS_DIR / job_id / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    saved: list[str] = []
    for f in files:
        # Take only the basename to defeat path traversal.
        name = Path(f.filename or "").name
        if not name:
            continue
        target = audio_dir / name
        with target.open("wb") as fh:
            shutil.copyfileobj(f.file, fh)
        saved.append(name)
    return {"saved": saved, "audio": audio_status(job_id)}


@app.delete("/jobs/{job_id}/audio/{index}")
async def delete_audio(job_id: str, index: int) -> dict[str, Any]:
    if job_id not in JOBS:
        raise HTTPException(404, "unknown job")
    audio_dir = JOBS_DIR / job_id / "audio"
    p = find_audio_for_slide(audio_dir, index)
    if p is None:
        raise HTTPException(404, "no audio for that slide")
    p.unlink()
    return {"deleted": p.name, "audio": audio_status(job_id)}


@app.post("/jobs/{job_id}/auto-narrate")
async def post_auto_narrate(
    job_id: str, overwrite: bool = False
) -> dict[str, Any]:
    """Fill in missing slide audio (or replace all if overwrite=true) with `say`."""
    if job_id not in JOBS:
        raise HTTPException(404, "unknown job")
    try:
        # Off-thread so we don't block the event loop while `say` runs.
        written = await asyncio.to_thread(auto_narrate, job_id, overwrite)
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(500, f"auto-narrate failed: {e}")
    return {"written": [p.name for p in written], "audio": audio_status(job_id)}


@app.post("/jobs/{job_id}/finalize")
async def post_finalize(job_id: str) -> dict[str, str]:
    if job_id not in JOBS:
        raise HTTPException(404, "unknown job")
    j = JOBS[job_id]
    j["stage"] = "final"
    j["status"] = "queued"
    j["progress"] = []
    j["error"] = None
    j["final_video"] = None

    async def run() -> None:
        j["status"] = "running"

        def log(msg: str) -> None:
            j["progress"].append(msg)

        try:
            result = await build_final(job_id, progress_cb=log)
            j["final_video"] = str(result.final_video_path)
            j["status"] = "done"
        except Exception as e:
            traceback.print_exc()
            j["status"] = "error"
            j["error"] = str(e)

    asyncio.create_task(run())
    return {"job_id": job_id}


@app.get("/jobs/{job_id}/video")
async def get_video(job_id: str) -> FileResponse:
    if job_id not in JOBS or not JOBS[job_id].get("final_video"):
        raise HTTPException(404, "final video not ready")
    return FileResponse(JOBS[job_id]["final_video"], media_type="video/mp4",
                        filename=f"{job_id}.mp4")
