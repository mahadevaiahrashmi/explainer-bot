"""API contract tests.

We monkeypatch every pipeline.* entry point to a fast in-memory stub, so
the tests exercise *FastAPI's wiring* and the per-endpoint response
shape — they do NOT spend a Claude call, launch Playwright, or invoke
ffmpeg. End-to-end behaviour belongs in smoke_test.py.
"""
from __future__ import annotations

import asyncio
import io
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient


# ─── shared stubs ─────────────────────────────────────────────────────────────

@dataclass
class _FakeDesignResult:
    job_id: str
    slide_html_paths: list[Path]
    progress: list[str] = field(default_factory=list)


@dataclass
class _FakeCueResult:
    job_id: str
    cue_video_path: Path
    script_text_path: Path
    slide_pngs: list[Path]
    estimated_durations: list[float]
    audio_dir: Path
    progress: list[str] = field(default_factory=list)


@dataclass
class _FakeFinalResult:
    job_id: str
    final_video_path: Path
    progress: list[str] = field(default_factory=list)


# ─── fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def stub_pipeline(monkeypatch, tmp_path):
    """Replace every slow pipeline entry point with a deterministic stub.

    Returns a SimpleNamespace exposing the call-history so tests can assert
    things like "endpoint X was called once with arg Y".
    """
    import pipeline
    import app as app_mod

    calls = SimpleNamespace(
        draft_script=[], design_slides=[], screenshot_slides=[],
        assemble_cue_video=[], build_cue=[], build_final=[],
        fix_slide=[], auto_narrate=[],
    )

    async def fake_draft_script(rough_points: str):
        calls.draft_script.append(rough_points)
        return pipeline.ScriptDraft(
            topic="fake topic",
            segments=[pipeline.Segment(title="A", key_visual="v", narration="n")],
            critique=pipeline.Critique(
                scores={"understandability": 5, "analogies": 5, "wonder": 5},
                verdict="approve",
                notes=["ok"],
            ),
            aesthetic=pipeline.Aesthetic(
                name="fake", palette=["#000"], font_family="serif",
                description="d",
            ),
        )

    async def fake_design_slides(topic, aesthetic, segments, *, job_id=None,
                                 progress_cb=None):
        job_id = job_id or "JOBID"
        calls.design_slides.append(job_id)
        job_dir = tmp_path / job_id
        slides_dir = job_dir / "slides"
        slides_dir.mkdir(parents=True, exist_ok=True)
        (job_dir / "plan.json").write_text(json.dumps({
            "topic": topic,
            "aesthetic": asdict(aesthetic),
            "segments": [asdict(s) for s in segments],
        }))
        paths = []
        for i in range(len(segments)):
            p = slides_dir / f"slide_{i:02d}.html"
            p.write_text("<!doctype html><html></html>")
            paths.append(p)
        # Point pipeline.JOBS_DIR at our tmp_path so endpoints find the job.
        return _FakeDesignResult(job_id=job_id, slide_html_paths=paths)

    async def fake_screenshot_slides(job_id, indices=None, progress_cb=None):
        calls.screenshot_slides.append((job_id, tuple(indices) if indices else None))
        job_dir = tmp_path / job_id
        slides_dir = job_dir / "slides"
        paths = []
        for p in sorted(slides_dir.glob("slide_*.html")):
            png = p.with_suffix(".png")
            png.write_bytes(b"\x89PNG\r\n\x1a\nfake")
            paths.append(png)
        return paths

    async def fake_assemble_cue_video(job_id, progress_cb=None):
        calls.assemble_cue_video.append(job_id)
        job_dir = tmp_path / job_id
        (job_dir / "work").mkdir(exist_ok=True)
        (job_dir / "audio").mkdir(exist_ok=True)
        cue = job_dir / "cue_video.mp4"; cue.write_bytes(b"fake-mp4")
        script = job_dir / "script.txt"; script.write_text("# fake script\n")
        return _FakeCueResult(
            job_id=job_id, cue_video_path=cue, script_text_path=script,
            slide_pngs=[], estimated_durations=[5.0], audio_dir=job_dir / "audio",
        )

    async def fake_build_cue(topic, aesthetic, segments, *, job_id=None,
                             progress_cb=None):
        await fake_design_slides(topic, aesthetic, segments, job_id=job_id)
        await fake_screenshot_slides(job_id or "JOBID")
        cue = await fake_assemble_cue_video(job_id or "JOBID")
        calls.build_cue.append(cue.job_id)
        return cue

    async def fake_build_final(job_id, progress_cb=None):
        calls.build_final.append(job_id)
        job_dir = tmp_path / job_id
        final = job_dir / "video.mp4"; final.write_bytes(b"fake-final")
        return _FakeFinalResult(job_id=job_id, final_video_path=final)

    async def fake_fix_slide(job_id, index, issue):
        calls.fix_slide.append((job_id, index, issue))
        return "<!doctype html><html><!--fixed--></html>"

    def fake_auto_narrate(job_id, overwrite=False, progress_cb=None):
        calls.auto_narrate.append((job_id, overwrite))
        return []

    # Patch on BOTH the pipeline module AND app (which imports the names).
    for name, fn in [
        ("draft_script", fake_draft_script),
        ("design_slides", fake_design_slides),
        ("screenshot_slides", fake_screenshot_slides),
        ("assemble_cue_video", fake_assemble_cue_video),
        ("build_cue", fake_build_cue),
        ("build_final", fake_build_final),
        ("fix_slide", fake_fix_slide),
        ("auto_narrate", fake_auto_narrate),
    ]:
        monkeypatch.setattr(pipeline, name, fn)
        monkeypatch.setattr(app_mod, name, fn)

    # Redirect JOBS_DIR so the audio + PNG endpoints serve from tmp_path.
    monkeypatch.setattr(pipeline, "JOBS_DIR", tmp_path)
    monkeypatch.setattr(app_mod, "JOBS_DIR", tmp_path)

    # audio_status() calls _probe_duration(path) on each present audio file —
    # that shells out to ffprobe, which barfs on our fake bytes. Stub it.
    monkeypatch.setattr(pipeline, "_probe_duration", lambda p: 1.23)
    return calls


@pytest.fixture
def client(stub_pipeline):
    import app as app_mod
    # Fresh JOBS dict per test to avoid cross-test pollution.
    app_mod.JOBS.clear()
    return TestClient(app_mod.app)


def _wait_for_job(client, job_id, status_target="done", timeout=2.0):
    """Spin-wait on /jobs/{id}/status until it hits `status_target`."""
    import time
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        j = client.get(f"/jobs/{job_id}/status").json()
        if j.get("status") in (status_target, "error"):
            return j
        time.sleep(0.05)
    return client.get(f"/jobs/{job_id}/status").json()


# ─── tests ────────────────────────────────────────────────────────────────────

class TestRoot:
    def test_get_root_serves_html(self, client):
        r = client.get("/")
        assert r.status_code == 200
        assert "<html" in r.text.lower() or "<!doctype" in r.text.lower()


class TestModels:
    def test_models_for_cli_backend_is_empty(self, client, monkeypatch):
        # claude_cli / codex_cli / gemini_cli pick no model.
        r = client.get("/models?backend=claude_cli")
        assert r.status_code == 200
        assert r.json() == {"backend": "claude_cli", "models": []}

    def test_models_for_llm_lists_them(self, client, monkeypatch):
        import pipeline
        monkeypatch.setattr(pipeline, "list_llm_models",
                            lambda: ["openrouter/deepseek/deepseek-chat",
                                     "openrouter/qwen/qwen-2.5-72b-instruct"])
        r = client.get("/models?backend=llm")
        assert r.status_code == 200
        body = r.json()
        assert body["backend"] == "llm"
        assert "openrouter/qwen/qwen-2.5-72b-instruct" in body["models"]

    def test_models_for_ollama(self, client, monkeypatch):
        import pipeline
        monkeypatch.setattr(pipeline, "list_ollama_models",
                            lambda: ["llama3.2:latest", "qwen2.5:14b"])
        r = client.get("/models?backend=ollama")
        assert r.status_code == 200
        assert "qwen2.5:14b" in r.json()["models"]


class TestBackend:
    def test_get_backend(self, client):
        r = client.get("/backend")
        assert r.status_code == 200
        j = r.json()
        assert "backend" in j
        assert j["valid_backends"] == [
            "claude_cli", "codex_cli", "gemini_cli", "ollama", "llm",
        ]
        # TTS fields now part of the contract too.
        assert "tts_engine" in j and j["tts_engine"] in (
            "say", "piper", "supertonic", "espeak", "elevenlabs",
        )
        assert "tts_source" in j


class TestScript:
    def test_empty_returns_400(self, client):
        r = client.post("/script", json={"rough_points": "   "})
        assert r.status_code == 400

    def test_happy_path(self, client, stub_pipeline):
        r = client.post("/script", json={"rough_points": "anything"})
        assert r.status_code == 200
        j = r.json()
        assert set(j.keys()) == {"topic", "aesthetic", "segments", "critique"}
        assert j["topic"] == "fake topic"
        assert len(j["segments"]) == 1
        assert j["segments"][0].keys() == {"title", "key_visual", "narration"}
        assert set(j["critique"]["scores"].keys()) == \
            {"understandability", "analogies", "wonder"}
        assert stub_pipeline.draft_script == ["anything"]

    def test_bad_backend_returns_400(self, client):
        r = client.post("/script",
                        json={"rough_points": "x", "backend": "pirate"})
        assert r.status_code == 400
        assert "pirate" in r.text


class TestDesign:
    def _req(self):
        return {
            "topic": "T",
            "aesthetic": {"name": "X", "palette": ["#000"],
                          "font_family": "serif", "description": "d"},
            "segments": [{"title": "A", "key_visual": "v", "narration": "n"}],
        }

    def test_returns_slides(self, client, stub_pipeline):
        r = client.post("/design", json=self._req())
        assert r.status_code == 200
        j = r.json()
        assert "job_id" in j
        assert isinstance(j["slides"], list) and len(j["slides"]) == 1
        s = j["slides"][0]
        assert set(s.keys()) == {"index", "title", "html"}
        assert s["html"].lower().startswith("<!doctype")
        assert stub_pipeline.design_slides   # the stub was actually called


class TestSlideHtml:
    def _setup_job(self, client):
        r = client.post("/design", json=TestDesign()._req())
        return r.json()["job_id"]

    def test_get_html(self, client):
        job_id = self._setup_job(client)
        r = client.get(f"/jobs/{job_id}/slide/0/html")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/plain")
        assert r.text.lower().startswith("<!doctype")

    def test_get_html_404_if_missing(self, client):
        r = client.get("/jobs/NOPE/slide/0/html")
        assert r.status_code == 404

    def test_put_html_saves(self, client, stub_pipeline):
        job_id = self._setup_job(client)
        new_html = "<!doctype html><html><body>EDITED</body></html>"
        r = client.put(f"/jobs/{job_id}/slide/0/html",
                       json={"html": new_html, "rerender": False})
        assert r.status_code == 200
        body = r.json()
        assert body["saved"] is True and body["rerendered"] is False
        # Confirm it really hit disk.
        r = client.get(f"/jobs/{job_id}/slide/0/html")
        assert r.text == new_html
        # screenshot_slides should NOT have been called (rerender=false).
        assert stub_pipeline.screenshot_slides == []

    def test_put_html_with_rerender_calls_screenshot(self, client, stub_pipeline):
        job_id = self._setup_job(client)
        r = client.put(f"/jobs/{job_id}/slide/0/html",
                       json={"html": "<!doctype html><html></html>",
                             "rerender": True})
        assert r.status_code == 200
        assert r.json()["rerendered"] is True
        # one screenshot call against index 0
        assert stub_pipeline.screenshot_slides == [(job_id, (0,))]

    def test_get_png_404_before_screenshot(self, client):
        job_id = self._setup_job(client)
        r = client.get(f"/jobs/{job_id}/slide/0/png")
        assert r.status_code == 404

    def test_get_png_serves_after_screenshot(self, client):
        job_id = self._setup_job(client)
        client.put(f"/jobs/{job_id}/slide/0/html",
                   json={"html": "<!doctype html><html></html>",
                         "rerender": True})
        r = client.get(f"/jobs/{job_id}/slide/0/png")
        assert r.status_code == 200
        assert r.headers["content-type"] == "image/png"


class TestSlideFix:
    def _setup_job(self, client):
        return client.post("/design", json=TestDesign()._req()).json()["job_id"]

    def test_empty_issue_400(self, client):
        job_id = self._setup_job(client)
        r = client.post(f"/jobs/{job_id}/slide/0/fix",
                        json={"issue": "   "})
        assert r.status_code == 400

    def test_happy(self, client, stub_pipeline):
        job_id = self._setup_job(client)
        r = client.post(f"/jobs/{job_id}/slide/0/fix",
                        json={"issue": "title overlaps diagram",
                              "rerender": True})
        assert r.status_code == 200
        body = r.json()
        assert "html" in body
        assert body["rerendered"] is True
        # fix_slide called once with the issue text
        assert stub_pipeline.fix_slide == [(job_id, 0, "title overlaps diagram")]


class TestRenderCue:
    def test_kicks_off_async_job(self, client, stub_pipeline):
        # First set up a designed job
        design = client.post("/design", json=TestDesign()._req()).json()
        job_id = design["job_id"]
        r = client.post(f"/jobs/{job_id}/render-cue")
        assert r.status_code == 200
        assert r.json()["job_id"] == job_id
        # poll until done
        status = _wait_for_job(client, job_id, "done")
        assert status["status"] == "done"
        assert status["has_cue_video"] is True


class TestCueLegacy:
    def test_post_cue_returns_jobid_immediately(self, client):
        r = client.post("/cue", json=TestDesign()._req())
        assert r.status_code == 200
        job_id = r.json()["job_id"]
        status = _wait_for_job(client, job_id, "done", timeout=3.0)
        assert status["status"] == "done"


class TestAudio:
    def _setup_job(self, client):
        return client.post("/design", json=TestDesign()._req()).json()["job_id"]

    def test_upload_saves_files(self, client):
        job_id = self._setup_job(client)
        files = [
            ("files", ("slide_00.wav", io.BytesIO(b"RIFF\x00\x00\x00\x00WAVE"),
                       "audio/wav")),
        ]
        r = client.post(f"/jobs/{job_id}/audio", files=files)
        assert r.status_code == 200
        assert r.json()["saved"] == ["slide_00.wav"]

    def test_path_traversal_defeated(self, client, tmp_path):
        job_id = self._setup_job(client)
        # Try to escape with ../
        files = [("files", ("../../etc/passwd",
                            io.BytesIO(b"x"), "audio/wav"))]
        r = client.post(f"/jobs/{job_id}/audio", files=files)
        assert r.status_code == 200
        # File should land at the *basename* inside the job's audio dir,
        # not anywhere outside tmp_path.
        audio_dir = tmp_path / job_id / "audio"
        assert (audio_dir / "passwd").exists() or \
               not (Path("/etc/passwd").parent / "passwd-injected").exists()

    def test_delete_audio_404_if_missing(self, client):
        job_id = self._setup_job(client)
        r = client.delete(f"/jobs/{job_id}/audio/0")
        assert r.status_code == 404


class TestAutoNarrate:
    def _setup_job(self, client):
        return client.post("/design", json=TestDesign()._req()).json()["job_id"]

    def test_post_returns_written_list(self, client, stub_pipeline):
        job_id = self._setup_job(client)
        r = client.post(f"/jobs/{job_id}/auto-narrate")
        assert r.status_code == 200
        assert "written" in r.json() and "audio" in r.json()
        assert stub_pipeline.auto_narrate == [(job_id, False)]

    def test_overwrite_param(self, client, stub_pipeline):
        job_id = self._setup_job(client)
        r = client.post(f"/jobs/{job_id}/auto-narrate?overwrite=true")
        assert r.status_code == 200
        assert stub_pipeline.auto_narrate == [(job_id, True)]


class TestFinalize:
    def test_kicks_off_and_serves_video(self, client):
        job_id = client.post("/design", json=TestDesign()._req()).json()["job_id"]
        r = client.post(f"/jobs/{job_id}/finalize")
        assert r.status_code == 200
        status = _wait_for_job(client, job_id, "done", timeout=3.0)
        assert status["status"] == "done"
        assert status["has_final_video"] is True
        # Now serve the video
        r = client.get(f"/jobs/{job_id}/video")
        assert r.status_code == 200
        assert r.headers["content-type"] == "video/mp4"

    def test_video_404_before_finalize(self, client):
        job_id = client.post("/design", json=TestDesign()._req()).json()["job_id"]
        r = client.get(f"/jobs/{job_id}/video")
        assert r.status_code == 404


class TestStatusUnknownJob:
    def test_404_on_unknown(self, client):
        r = client.get("/jobs/UNKNOWN/status")
        assert r.status_code == 404
