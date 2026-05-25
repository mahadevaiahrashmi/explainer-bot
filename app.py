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
    audio_status,
    build_cue,
    build_final,
    draft_script,
    find_audio_for_slide,
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


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def index() -> str:
    return (TEMPLATES / "chat.html").read_text()


@app.post("/script")
async def post_script(req: ScriptRequest) -> dict[str, Any]:
    if not req.rough_points.strip():
        raise HTTPException(400, "rough_points cannot be empty")
    try:
        draft = await draft_script(req.rough_points)
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(500, f"script generation failed: {e}")
    return {
        "topic": draft.topic,
        "aesthetic": asdict(draft.aesthetic),
        "segments": [asdict(s) for s in draft.segments],
        "critique": asdict(draft.critique),
    }


@app.post("/cue")
async def post_cue(req: CueRequest) -> dict[str, str]:
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
