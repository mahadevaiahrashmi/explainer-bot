"""End-to-end pipeline: rough points -> cue video -> audio -> final video.

External dependencies:
  - ffmpeg / ffprobe                      (required, on PATH)
  - say                                   (macOS built-in TTS, optional, only
                                            used by auto_narrate)
  - playwright + chromium                 (python package + browser)
  - ONE of three LLM backends             (auto-detected, see below)

LLM backends (controlled by ``BACKEND`` env var, default: auto-detect):

  ``claude_cli``  — shells out to ``claude -p``. Uses the user's Claude Code
                    subscription, no API key needed. Preferred default if
                    ``claude`` is on PATH.

  ``ollama``      — POSTs to ``OLLAMA_URL`` (default http://localhost:11434).
                    Free, local, no internet. Pick the model with
                    ``OLLAMA_MODEL`` (default ``llama3.2``).

  ``llm``         — shells out to ``llm -m $LLM_MODEL``. Provider-agnostic
                    CLI from Simon Willison. Default model picked by your
                    ``llm`` configuration. Set ``LLM_MODEL=claude-sonnet-4-5``
                    (or ``gpt-4.1``, ``gemini-2.0-flash``, ...) to override.
                    Requires you've run ``llm keys set <provider>``.

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
import contextvars
import json
import os
import re
import shutil
import subprocess
import sys
import textwrap
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import httpx
from playwright.async_api import async_playwright

from prompts import (
    AESTHETIC_PICKER_PROMPT,
    CRITIC_PROMPT,
    SLIDE_DESIGNER_PROMPT,
    SLIDE_FIXER_PROMPT,
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
# LLM backend dispatch — three options:
#   1) claude_cli  (Claude Code subscription, no API key)
#   2) ollama      (local, free, no internet)
#   3) llm         (provider-agnostic; cloud API key required)
#
# Picked by ``BACKEND`` env var, otherwise auto-detected on first call.
# ---------------------------------------------------------------------------

VALID_BACKENDS = ("claude_cli", "codex_cli", "gemini_cli", "ollama", "llm")
DEFAULT_OLLAMA_MODEL = "llama3.2"
DEFAULT_OLLAMA_URL = "http://localhost:11434"
LLM_TIMEOUT_S = CLAUDE_TIMEOUT_S   # kept as old name elsewhere; same value

_BACKEND_CACHE: str | None = None

# Per-request overrides. Set these in a request handler (or a CLI flag handler)
# and every llm_call() in the same async context will honour them. Because we
# use asyncio.create_task() for background jobs, the ContextVar snapshot is
# preserved into those tasks too.
_REQUEST_BACKEND: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "explainer_request_backend", default=None,
)
_REQUEST_MODEL: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "explainer_request_model", default=None,
)
_REQUEST_TTS_ENGINE: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "explainer_request_tts_engine", default=None,
)


def set_request_overrides(
    backend: str | None = None,
    model: str | None = None,
    tts_engine: str | None = None,
) -> None:
    """Override the LLM backend / model / TTS engine for the current async
    context only.

    Pass empty / None to leave the default in effect. Call this at the start
    of every request handler that wants to honour user-supplied picks.
    """
    b = (backend or "").strip().lower() or None
    if b and b not in VALID_BACKENDS:
        raise RuntimeError(f"Unknown backend {b!r}; pick one of {', '.join(VALID_BACKENDS)}.")
    t = (tts_engine or "").strip().lower() or None
    if t and t not in VALID_TTS_ENGINES:
        raise RuntimeError(
            f"Unknown TTS engine {t!r}; pick one of {', '.join(VALID_TTS_ENGINES)}."
        )
    _REQUEST_BACKEND.set(b)
    _REQUEST_MODEL.set((model or "").strip() or None)
    _REQUEST_TTS_ENGINE.set(t)


def _detect_backend() -> str:
    """Pick a backend automatically. Preference order:
        claude_cli → codex_cli → gemini_cli → ollama → llm

    Reasoning: subscription-bundled CLIs first (free at point of use, no API
    key), then local Ollama (free but needs a running daemon), then the
    paid-API catch-all via `llm`.
    """
    if shutil.which("claude"):
        return "claude_cli"
    if shutil.which("codex"):
        return "codex_cli"
    if shutil.which("gemini"):
        return "gemini_cli"
    if _ollama_reachable():
        return "ollama"
    if shutil.which("llm") or (Path(sys.executable).parent / "llm").exists():
        return "llm"
    raise RuntimeError(
        "No LLM backend available. Install ONE of:\n"
        "  • Claude Code      (gives you `claude` CLI; uses your subscription)\n"
        "                     https://claude.com/code\n"
        "  • OpenAI Codex CLI (uses your ChatGPT Plus / Pro subscription)\n"
        "                     npm install -g @openai/codex     # then `codex login`\n"
        "  • Google Gemini CLI (uses your Google AI Pro subscription, or free tier)\n"
        "                     npm install -g @google/gemini-cli  # then `gemini auth`\n"
        "  • Ollama           (free, local, no internet)\n"
        "                     brew install ollama && ollama pull llama3.2\n"
        "                     ollama serve\n"
        "  • An API-key path  (any provider via the `llm` CLI — already in our deps)\n"
        "                     llm keys set claude     # or openai, gemini, etc.\n"
        "                     export LLM_MODEL=claude-sonnet-4-5\n"
        "Then re-run.  You can also force one with "
        "BACKEND=claude_cli|codex_cli|gemini_cli|ollama|llm."
    )


def _ollama_reachable() -> bool:
    url = os.environ.get("OLLAMA_URL", DEFAULT_OLLAMA_URL)
    try:
        with httpx.Client(timeout=0.4) as client:
            r = client.get(f"{url}/api/tags")
            return r.status_code == 200
    except Exception:
        return False


def get_backend() -> str:
    """Return the resolved backend name, caching the first decision."""
    global _BACKEND_CACHE
    if _BACKEND_CACHE:
        return _BACKEND_CACHE
    chosen = (os.environ.get("BACKEND") or "").lower().strip()
    if chosen and chosen not in VALID_BACKENDS:
        raise RuntimeError(
            f"Unknown BACKEND={chosen!r}. Pick one of: {', '.join(VALID_BACKENDS)}."
        )
    _BACKEND_CACHE = chosen or _detect_backend()
    return _BACKEND_CACHE


async def llm_call(system_prompt: str, user_message: str) -> str:
    """Dispatch to the chosen backend. Returns the model's raw text reply.

    The backend is the request-scoped override if set (see
    `set_request_overrides`), otherwise the env-var-or-auto-detected default.
    """
    b = _REQUEST_BACKEND.get() or get_backend()
    m = _REQUEST_MODEL.get()
    if b == "claude_cli":
        return await _call_claude_cli(system_prompt, user_message)
    if b == "codex_cli":
        return await _call_codex_cli(system_prompt, user_message)
    if b == "gemini_cli":
        return await _call_gemini_cli(system_prompt, user_message)
    if b == "ollama":
        return await _call_ollama(system_prompt, user_message, model=m)
    if b == "llm":
        return await _call_llm_cli(system_prompt, user_message, model=m)
    raise RuntimeError(f"unreachable: backend {b!r}")


def current_backend_info() -> dict[str, str | None]:
    """What backend / model / TTS engine would the next llm_call (and
    auto_narrate) use, right now?"""
    b = _REQUEST_BACKEND.get() or get_backend()
    m = _REQUEST_MODEL.get()
    src = "request" if _REQUEST_BACKEND.get() else "auto"
    # Build the LLM-side info first.
    if b in ("claude_cli", "codex_cli", "gemini_cli"):
        info: dict[str, str | None] = {"backend": b, "model": None, "source": src}
    elif b == "ollama":
        info = {
            "backend": b,
            "model": m or os.environ.get("OLLAMA_MODEL", DEFAULT_OLLAMA_MODEL),
            "source": "request" if (m or _REQUEST_BACKEND.get()) else "env",
        }
    elif b == "llm":
        info = {
            "backend": b,
            "model": m or os.environ.get("LLM_MODEL"),
            "source": "request" if (m or _REQUEST_BACKEND.get()) else "env",
        }
    else:
        info = {"backend": b, "model": None, "source": "unknown"}
    # TTS side — same source-tag convention.
    tts_req = _REQUEST_TTS_ENGINE.get()
    info["tts_engine"] = _resolve_tts_engine()
    if tts_req:
        info["tts_source"] = "request"
    elif os.environ.get("TTS_ENGINE"):
        info["tts_source"] = "env"
    else:
        info["tts_source"] = "default"
    return info


# Back-compat alias — old callers used pipeline.claude(...).
claude = llm_call


# --- claude_cli backend ----------------------------------------------------

async def _call_claude_cli(system_prompt: str, user_message: str) -> str:
    proc = await asyncio.create_subprocess_exec(
        "claude", "-p", "--append-system-prompt", system_prompt, user_message,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=LLM_TIMEOUT_S)
    except asyncio.TimeoutError:
        proc.kill()
        raise RuntimeError(f"claude CLI timed out after {LLM_TIMEOUT_S}s")
    if proc.returncode != 0:
        raise RuntimeError(f"claude CLI failed: {stderr.decode(errors='replace')[:500]}")
    return stdout.decode(errors="replace").strip()


# --- codex_cli backend (OpenAI's `codex` CLI; ChatGPT subscription) --------

def _combined_prompt(system_prompt: str, user_message: str) -> str:
    """Codex and Gemini CLIs both take ONE prompt arg, not separate system /
    user fields. Combine them with a clear delimiter."""
    return f"{system_prompt}\n\n---\n\n{user_message}"


async def _call_codex_cli(system_prompt: str, user_message: str) -> str:
    if not shutil.which("codex"):
        raise RuntimeError(
            "`codex` CLI not on PATH. Install with one of:\n"
            "  npm install -g @openai/codex\n"
            "  brew install codex            # if available in your tap\n"
            "Then run `codex login` to authenticate against your ChatGPT "
            "Plus / Pro / Team subscription. Verify with `codex --version`.\n"
            "If your codex version uses a different non-interactive command, "
            "override via CODEX_CMD env var (e.g. CODEX_CMD='codex exec')."
        )
    # Default non-interactive form is `codex exec <prompt>`. Override the
    # whole command via CODEX_CMD if the syntax differs in your installed
    # version.
    cmd_str = os.environ.get("CODEX_CMD", "codex exec")
    cmd = cmd_str.split()
    proc = await asyncio.create_subprocess_exec(
        *cmd, _combined_prompt(system_prompt, user_message),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=LLM_TIMEOUT_S)
    except asyncio.TimeoutError:
        proc.kill()
        raise RuntimeError(f"`codex` CLI timed out after {LLM_TIMEOUT_S}s")
    if proc.returncode != 0:
        msg = stderr.decode(errors="replace")[:500]
        hint = ""
        if "login" in msg.lower() or "auth" in msg.lower():
            hint = "\nHint: run `codex login` to authenticate first."
        elif "unknown command" in msg.lower() or "no such" in msg.lower():
            hint = (f"\nHint: your `codex` version may not support `{cmd_str}`. "
                    f"Try setting CODEX_CMD to whatever your version uses for "
                    f"non-interactive one-shot prompts.")
        raise RuntimeError(f"`codex` CLI failed: {msg}{hint}")
    return stdout.decode(errors="replace").strip()


# --- gemini_cli backend (Google's `gemini` CLI; Google AI Pro / free tier) -

async def _call_gemini_cli(system_prompt: str, user_message: str) -> str:
    if not shutil.which("gemini"):
        raise RuntimeError(
            "`gemini` CLI not on PATH. Install with:\n"
            "  npm install -g @google/gemini-cli\n"
            "Then run `gemini auth` (or set GEMINI_API_KEY) to authenticate.\n"
            "Verify with `gemini --version`.\n"
            "If your gemini version uses a different non-interactive flag, "
            "override via GEMINI_CMD env var (e.g. GEMINI_CMD='gemini -p')."
        )
    # Default non-interactive form is `gemini -p <prompt>`. Override the
    # whole command via GEMINI_CMD if needed.
    cmd_str = os.environ.get("GEMINI_CMD", "gemini -p")
    cmd = cmd_str.split()
    proc = await asyncio.create_subprocess_exec(
        *cmd, _combined_prompt(system_prompt, user_message),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=LLM_TIMEOUT_S)
    except asyncio.TimeoutError:
        proc.kill()
        raise RuntimeError(f"`gemini` CLI timed out after {LLM_TIMEOUT_S}s")
    if proc.returncode != 0:
        msg = stderr.decode(errors="replace")[:500]
        hint = ""
        if "api_key" in msg.lower() or "auth" in msg.lower():
            hint = "\nHint: run `gemini auth` or set GEMINI_API_KEY first."
        raise RuntimeError(f"`gemini` CLI failed: {msg}{hint}")
    return stdout.decode(errors="replace").strip()


# --- ollama backend --------------------------------------------------------

async def _call_ollama(system_prompt: str, user_message: str, *, model: str | None = None) -> str:
    model = model or os.environ.get("OLLAMA_MODEL", DEFAULT_OLLAMA_MODEL)
    url = os.environ.get("OLLAMA_URL", DEFAULT_OLLAMA_URL)
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        "stream": False,
        # Lower temperature gives the JSON-output prompts a better chance.
        "options": {"temperature": 0.4},
    }
    try:
        async with httpx.AsyncClient(timeout=LLM_TIMEOUT_S) as client:
            r = await client.post(f"{url}/api/chat", json=payload)
    except httpx.RequestError as e:
        raise RuntimeError(
            f"Ollama at {url} unreachable ({e}). Is `ollama serve` running, "
            f"and is OLLAMA_MODEL={model} pulled? `ollama pull {model}`"
        )
    if r.status_code != 200:
        raise RuntimeError(f"Ollama {r.status_code}: {r.text[:500]}")
    data = r.json()
    return (data.get("message", {}).get("content") or "").strip()


# --- llm CLI backend -------------------------------------------------------

def _llm_executable() -> str:
    """Prefer the venv-local llm so the bundled llm-anthropic plugin is found."""
    candidate = Path(sys.executable).parent / "llm"
    if candidate.exists():
        return str(candidate)
    found = shutil.which("llm")
    if found:
        return found
    raise RuntimeError("`llm` CLI not found. Run `uv sync` to install it.")


async def _call_llm_cli(system_prompt: str, user_message: str, *, model: str | None = None) -> str:
    args = [_llm_executable()]
    model = model or os.environ.get("LLM_MODEL")
    if model:
        args.extend(["-m", model])
    args.extend(["--system", system_prompt, user_message])
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=LLM_TIMEOUT_S)
    except asyncio.TimeoutError:
        proc.kill()
        raise RuntimeError(f"`llm` CLI timed out after {LLM_TIMEOUT_S}s")
    if proc.returncode != 0:
        msg = stderr.decode(errors="replace")[:500]
        hint = ""
        if "key" in msg.lower():
            hint = ("\nHint: run `llm keys set <provider>` (e.g. `llm keys set claude` "
                    "for Anthropic) and set LLM_MODEL to a supported model.")
        raise RuntimeError(f"`llm` CLI failed: {msg}{hint}")
    return stdout.decode(errors="replace").strip()


_FENCE_RE = re.compile(r"^```[a-zA-Z]*\s*|\s*```$", re.MULTILINE)


def _strip_fences(text: str) -> str:
    return _FENCE_RE.sub("", text).strip()


def _extract_json(text: str) -> Any:
    """Best-effort JSON extraction. Returns whatever JSON the model produced.

    Strategy:
      1. Try to parse the whole (de-fenced) text.
      2. Otherwise find the first occurrence of `{` or `[` (whichever is
         leftmost) and parse the balanced block starting there. Keeps trying
         later candidates if a balanced block fails to parse.
    """
    text = _strip_fences(text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # All candidate opener positions, earliest first.
    candidates: list[tuple[int, str, str]] = []
    for opener, closer in (("{", "}"), ("[", "]")):
        idx = text.find(opener)
        if idx != -1:
            candidates.append((idx, opener, closer))
    candidates.sort()  # earliest position wins, e.g. "{...}" before "[...]"
    last_err: Exception | None = None
    for start, opener, closer in candidates:
        depth = 0
        for i in range(start, len(text)):
            if text[i] == opener:
                depth += 1
            elif text[i] == closer:
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start : i + 1])
                    except json.JSONDecodeError as e:
                        last_err = e
                        break  # try the next candidate
    raise ValueError(
        f"Could not parse JSON from model output (last error: {last_err}). "
        f"First 300 chars: {text[:300]!r}"
    )


_TITLE_KEYS     = ("title", "heading", "header", "name", "slide_title")
_VISUAL_KEYS    = ("key_visual", "keyvisual", "visual", "image", "diagram",
                   "description", "visual_description", "key_visual_description")
_NARRATION_KEYS = ("narration", "script", "voiceover", "speech", "text",
                   "body", "spoken", "narration_text")


def _first(d: dict[str, Any], keys: tuple[str, ...]) -> Any:
    """Return the first value in `d` whose key matches `keys`, else None.

    Match is case-insensitive on the dict keys.
    """
    lower = {k.lower(): v for k, v in d.items() if isinstance(k, str)}
    for k in keys:
        if k in lower:
            return lower[k]
    return None


def _coerce_segments(raw: Any) -> list["Segment"]:
    """Build a list[Segment] from whatever the writer returned.

    Tolerates the common shapes that weaker models emit:
      - aliased keys (`script` / `text` / `body` for narration;
        `visual` / `description` for key_visual; `heading` for title)
      - the whole thing wrapped in a dict (e.g. {"segments":[...]})
      - missing keys filled with sensible defaults so the rest of the
        pipeline can still run
    Raises a clear error only if there isn't a single usable segment.
    """
    # Sometimes the model wraps the array: {"segments":[...]} or
    # {"script":[...]} — unwrap those before iterating.
    if isinstance(raw, dict):
        for k in ("segments", "slides", "script", "items"):
            v = raw.get(k)
            if isinstance(v, list):
                raw = v
                break
        else:
            # Single segment as a dict? Wrap so it's still iterable.
            raw = [raw]
    if not isinstance(raw, list):
        raise ValueError(
            f"Expected the writer to return a list of segments, got "
            f"{type(raw).__name__}. First 300 chars: {str(raw)[:300]!r}"
        )

    out: list[Segment] = []
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            # Sometimes the model emits ["text", "text", ...] — skip strings.
            continue
        title     = _first(item, _TITLE_KEYS)
        visual    = _first(item, _VISUAL_KEYS)
        narration = _first(item, _NARRATION_KEYS)
        # Last resort: any string value at all becomes narration.
        if narration is None:
            string_vals = [v for v in item.values() if isinstance(v, str) and v.strip()]
            if string_vals:
                narration = max(string_vals, key=len)
        if not (isinstance(title, str) and title.strip()) and \
           not (isinstance(narration, str) and narration.strip()):
            # No title AND no narration — useless segment, drop it.
            continue
        out.append(Segment(
            title=str(title or f"Slide {i + 1}").strip(),
            key_visual=str(visual or "An illustrative diagram for this slide").strip(),
            narration=str(narration or title or "").strip(),
        ))
    if not out:
        raise ValueError(
            f"Writer returned no usable segments. The model likely didn't "
            f"follow the JSON schema. Try a bigger Ollama model "
            f"(e.g. qwen2.5:14b) or a different backend. "
            f"Raw input: {str(raw)[:300]!r}"
        )
    return out


_AESTHETIC_NAME_KEYS    = ("name", "title", "aesthetic", "style")
_AESTHETIC_PAL_KEYS     = ("palette", "colors", "colours", "color_palette")
_AESTHETIC_FONT_KEYS    = ("font_family", "font", "typeface", "fonts")
_AESTHETIC_DESC_KEYS    = ("description", "desc", "rationale", "notes")


def _coerce_aesthetic(aes: dict[str, Any]) -> "Aesthetic":
    """Build an Aesthetic from a parsed dict, filling sensible defaults if
    the model omitted fields. Accepts a few common key-name variants."""
    name = _first(aes, _AESTHETIC_NAME_KEYS)
    pal  = _first(aes, _AESTHETIC_PAL_KEYS)
    font = _first(aes, _AESTHETIC_FONT_KEYS)
    desc = _first(aes, _AESTHETIC_DESC_KEYS)

    # Palette: accept list[str], or list[dict{hex|color}], or comma-string.
    palette: list[str] = []
    if isinstance(pal, list):
        for entry in pal:
            if isinstance(entry, str):
                palette.append(entry)
            elif isinstance(entry, dict):
                v = _first(entry, ("hex", "color", "colour", "value"))
                if isinstance(v, str):
                    palette.append(v)
    elif isinstance(pal, str):
        palette = [p.strip() for p in pal.split(",") if p.strip()]
    if not palette:
        palette = ["#0d1117", "#e6edf3", "#58a6ff"]   # safe default

    return Aesthetic(
        name=str(name or "Default").strip(),
        palette=palette,
        font_family=str(font or "-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif").strip(),
        description=str(desc or "").strip(),
    )


def _coerce_critique(crit: dict[str, Any]) -> "Critique":
    """Build a Critique from a parsed dict, accepting a few shape variations
    that smaller models sometimes produce."""
    # `scores` should be a dict; some models emit a list like
    # [{"understandability":4}, {"analogies":5}, {"wonder":4}] — flatten it.
    raw_scores = crit.get("scores", {})
    if isinstance(raw_scores, list):
        flat: dict[str, int] = {}
        for item in raw_scores:
            if isinstance(item, dict):
                flat.update(item)
        raw_scores = flat
    if not isinstance(raw_scores, dict):
        raise ValueError(f"Critique `scores` should be a dict, got {type(raw_scores).__name__}: {raw_scores!r}")
    # Coerce values to int (models occasionally return "4/5" or "4").
    scores: dict[str, int] = {}
    for k, v in raw_scores.items():
        if isinstance(v, str):
            # Pull the first integer-looking token.
            m = re.search(r"\d+", v)
            v = int(m.group()) if m else 0
        try:
            scores[str(k)] = int(v)
        except (TypeError, ValueError):
            scores[str(k)] = 0

    verdict = str(crit.get("verdict", "revise")).strip().lower()
    if verdict not in ("approve", "revise"):
        # Map common variants.
        verdict = "approve" if verdict.startswith("appr") else "revise"

    notes_raw = crit.get("notes", [])
    if isinstance(notes_raw, str):
        notes = [notes_raw]
    elif isinstance(notes_raw, list):
        notes = [str(n) for n in notes_raw]
    else:
        notes = [str(notes_raw)]

    return Critique(scores=scores, verdict=verdict, notes=notes)


def _extract_json_obj(text: str, *, kind: str = "object") -> dict[str, Any]:
    """Like _extract_json but enforces a JSON object.

    Small / weaker models sometimes wrap their output in a single-element
    list (`[{...}]`) even when the schema asked for `{...}`. We unwrap
    that case quietly. Anything else that isn't a dict raises a clear
    error pointing at the model output.
    """
    data = _extract_json(text)
    if isinstance(data, list):
        if len(data) == 1 and isinstance(data[0], dict):
            return data[0]
        raise ValueError(
            f"Expected JSON {kind} from the model, got a list of {len(data)} "
            f"items. The model likely doesn't follow JSON-object schemas — "
            f"try a bigger Ollama model (e.g. qwen2.5:14b) or a different "
            f"backend. First 300 chars: {str(data)[:300]!r}"
        )
    if not isinstance(data, dict):
        raise ValueError(
            f"Expected JSON {kind} from the model, got {type(data).__name__}. "
            f"First 300 chars: {str(data)[:300]!r}"
        )
    return data


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

    segments = _coerce_segments(_extract_json(segments_raw))
    aesthetic = _coerce_aesthetic(_extract_json_obj(aesthetic_raw, kind="aesthetic object"))

    critic_user = "Script to review (JSON array of slide segments):\n\n" + json.dumps(
        [s.__dict__ for s in segments], indent=2
    )
    critique_raw = await claude(CRITIC_PROMPT, critic_user)
    crit = _extract_json_obj(critique_raw, kind="critique object")
    critique = _coerce_critique(crit)

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


# Minimum margin from the 1920×1080 frame edges (matches LAYOUT RULES L2
# in SLIDE_DESIGNER_PROMPT). An element closer than this counts as a
# "too close to edge" violation.
EDGE_MARGIN_PX = 80
# Ignore overlaps where the intersecting elements have a parent / child
# relationship (an SVG inside its container, a span inside a heading)
# or where both are decorative / structural (html, body, div with no text).
_OVERLAP_IGNORE_TAGS = {"html", "body"}


async def _detect_overlaps(page) -> list[str]:
    """Run in-browser geometry checks on the just-laid-out slide.

    Returns a list of human-readable problem strings. Empty list means
    the layout passed all checks (no pair overlaps, all elements at
    least EDGE_MARGIN_PX from each frame edge).

    These problems are reported via the progress callback but do NOT
    fail the screenshot. The user can review and use the in-app
    "ask bot to fix this slide" flow to address them.
    """
    js = """
    ([W, H, EDGE, IGNORE]) => {
        const out = [];
        // Only consider elements that have text content OR are an svg/img
        // (i.e. things the user actually sees and cares about overlap of).
        const all = Array.from(document.body.querySelectorAll('*'))
            .filter(el => !IGNORE.includes(el.tagName.toLowerCase()))
            .filter(el => {
                const r = el.getBoundingClientRect();
                if (r.width === 0 || r.height === 0) return false;
                const hasText = (el.textContent || '').trim().length > 0;
                const tag = el.tagName.toLowerCase();
                return hasText || tag === 'svg' || tag === 'img';
            });

        // Edge-margin check: anything within EDGE of the frame edge.
        for (const el of all) {
            const r = el.getBoundingClientRect();
            const tag = el.tagName.toLowerCase();
            const tag_summary = tag + (el.id ? '#' + el.id : '')
                + (el.className && typeof el.className === 'string'
                    ? '.' + el.className.split(/\\s+/).filter(Boolean).slice(0,2).join('.')
                    : '');
            const t = (el.textContent || '').replace(/\\s+/g, ' ').trim().slice(0, 30);
            const label = t ? `${tag_summary} "${t}"` : tag_summary;
            if (r.top    < EDGE)            out.push(`too close to TOP edge (y=${Math.round(r.top)}): ${label}`);
            if (r.left   < EDGE)            out.push(`too close to LEFT edge (x=${Math.round(r.left)}): ${label}`);
            if (r.right  > W - EDGE)        out.push(`too close to RIGHT edge (x=${Math.round(r.right)}): ${label}`);
            if (r.bottom > H - EDGE)        out.push(`too close to BOTTOM edge (y=${Math.round(r.bottom)}): ${label}`);
        }

        // Pairwise overlap check. Skip pairs where one element contains
        // the other (e.g. a span inside its parent heading).
        function intersects(a, b) {
            return !(a.right  <= b.left ||
                     a.bottom <= b.top  ||
                     a.left   >= b.right ||
                     a.top    >= b.bottom);
        }
        for (let i = 0; i < all.length; i++) {
            for (let j = i + 1; j < all.length; j++) {
                const A = all[i], B = all[j];
                if (A.contains(B) || B.contains(A)) continue;
                const ra = A.getBoundingClientRect();
                const rb = B.getBoundingClientRect();
                if (intersects(ra, rb)) {
                    const ta = (A.textContent || '').replace(/\\s+/g,' ').trim().slice(0, 30);
                    const tb = (B.textContent || '').replace(/\\s+/g,' ').trim().slice(0, 30);
                    out.push(`OVERLAP: <${A.tagName.toLowerCase()}> "${ta}" ⨯ <${B.tagName.toLowerCase()}> "${tb}"`);
                }
            }
        }
        return out;
    }
    """
    try:
        return await page.evaluate(js, [VIDEO_W, VIDEO_H, EDGE_MARGIN_PX,
                                        sorted(_OVERLAP_IGNORE_TAGS)])
    except Exception:  # JS error etc. — don't break the pipeline.
        return []


async def _screenshot_slide(html: str, out_png: Path, browser,
                            progress_cb=None, slide_label: str = "") -> None:
    page = await browser.new_page(viewport={"width": VIDEO_W, "height": VIDEO_H})
    try:
        await page.set_content(html, wait_until="networkidle")
        # Run overlap / edge-margin checks BEFORE the screenshot so the
        # user gets a heads-up if the slide-designer prompt didn't respect
        # the no-overlap rules (which it should, but smaller models drift).
        if progress_cb:
            problems = await _detect_overlaps(page)
            if problems:
                progress_cb(f"  ⚠ {slide_label or out_png.stem}: "
                            f"{len(problems)} layout issue(s) detected:")
                for p in problems[:5]:    # cap the spam at 5 lines per slide
                    progress_cb(f"      • {p}")
                if len(problems) > 5:
                    progress_cb(f"      … and {len(problems) - 5} more")
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


async def fix_slide(job_id: str, index: int, issue: str) -> str:
    """Ask Claude to fix a reported visual issue in one slide and return new HTML.

    The new HTML is written to disk by this function (so callers don't have to
    remember to call `update_slide_html` themselves). Caller is still
    responsible for re-screenshotting via `screenshot_slides([index])`.
    """
    issue = issue.strip()
    if not issue:
        raise ValueError("issue description cannot be empty")
    job_dir = _job_dir(job_id)
    if not (job_dir / "plan.json").exists():
        raise FileNotFoundError(f"no plan for job {job_id}")
    _, aesthetic, segments = _load_plan(job_dir)
    if not 0 <= index < len(segments):
        raise IndexError(f"slide index {index} out of range (0..{len(segments) - 1})")
    segment = segments[index]
    current_html = get_slide_html(job_id, index)

    user_message = textwrap.dedent(
        f"""
        SLIDE TITLE: {segment.title}
        KEY_VISUAL:  {segment.key_visual}

        CHOSEN AESTHETIC:
        {_aesthetic_brief(aesthetic)}

        USER ISSUE:
        {issue}

        CURRENT HTML:
        {current_html}

        Produce the corrected HTML now.
        """
    ).strip()
    new_html = _strip_fences(await claude(SLIDE_FIXER_PROMPT, user_message))
    _slide_html_path(job_dir, index).write_text(new_html)
    return new_html


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
                await _screenshot_slide(
                    html_path.read_text(), png, browser,
                    progress_cb=progress_cb,
                    slide_label=f"slide {i + 1}/{len(segments)}",
                )
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

# TTS engines for auto_narrate. Pick with TTS_ENGINE env var.
#   say         — macOS built-in. Free, no setup. Default. Robotic but reliable.
#   piper       — open-source neural TTS (Hugging Face piper-tts). Higher quality
#                 than `say` but needs a Python install + a voice file download.
#                 Free and fully offline once set up.
#   supertonic  — open-source on-device TTS (Supertone). Pip-installable; the
#                 SDK auto-downloads its ONNX models (~260MB) on first use.
#                 Free and fully offline. Often the best-sounding free option. ✨
#   espeak      — eSpeak-NG fallback. Truly free, available on every OS, very
#                 robotic. Useful when nothing else is an option.
VALID_TTS_ENGINES = ("say", "piper", "supertonic", "espeak")


def find_audio_for_slide(audio_dir: Path, index: int) -> Path | None:
    """Look for slide_{index:02d}.{ext} in `audio_dir`."""
    stem = f"slide_{index:02d}"
    for p in sorted(audio_dir.iterdir()):
        if p.is_file() and p.stem == stem and p.suffix.lower() in _AUDIO_EXTS:
            return p
    return None


def _resolve_tts_engine() -> str:
    """Pick the TTS engine. Order of precedence:
        1. per-request override via `set_request_overrides(tts_engine=...)`
        2. TTS_ENGINE env var
        3. default `say` (macOS built-in, always present)
    """
    req = _REQUEST_TTS_ENGINE.get()
    if req:
        return req
    chosen = (os.environ.get("TTS_ENGINE") or "").lower().strip()
    if chosen and chosen not in VALID_TTS_ENGINES:
        raise RuntimeError(
            f"Unknown TTS_ENGINE={chosen!r}. Pick one of {', '.join(VALID_TTS_ENGINES)}."
        )
    return chosen or "say"


def _synthesize_say(text: str, out_path: Path) -> None:
    """macOS built-in `say` → AIFF."""
    subprocess.run(
        ["say", "-v", SAY_VOICE, "-r", str(SAY_RATE_WPM),
         "-o", str(out_path), text],
        check=True,
    )


def _piper_voice_path() -> Path:
    """Locate a Piper voice file (.onnx). Order:
        1. PIPER_VOICE env var if set
        2. first .onnx found in ~/piper-voices/ (alphabetical)
    """
    env = os.environ.get("PIPER_VOICE")
    if env:
        p = Path(env).expanduser()
        if not p.is_file():
            raise RuntimeError(f"PIPER_VOICE={env!r} does not exist.")
        return p
    voices_dir = Path.home() / "piper-voices"
    if voices_dir.is_dir():
        for v in sorted(voices_dir.glob("*.onnx")):
            return v
    raise RuntimeError(
        "No Piper voice found. Either:\n"
        "  • set PIPER_VOICE=/abs/path/to/voice.onnx, or\n"
        "  • drop one .onnx (+ matching .onnx.json) into ~/piper-voices/.\n"
        "Voices: https://huggingface.co/rhasspy/piper-voices/tree/main\n"
        "Recommended starter: en_US-lessac-medium (about 30 MB)."
    )


def _synthesize_piper(text: str, out_path: Path) -> None:
    """Open-source Piper neural TTS → WAV."""
    if not shutil.which("piper"):
        raise RuntimeError(
            "`piper` CLI not on PATH. Install with one of:\n"
            "  pipx install piper-tts\n"
            "  uv tool install piper-tts\n"
            "  pip install piper-tts        (in your venv)\n"
            "Then run a voice through it to confirm: "
            "`echo hello | piper -m ~/piper-voices/en_US-lessac-medium.onnx -f /tmp/x.wav`"
        )
    voice = _piper_voice_path()
    out_path = out_path.with_suffix(".wav")  # Piper writes WAV
    proc = subprocess.run(
        ["piper", "-m", str(voice), "-f", str(out_path)],
        input=text, text=True, check=True,
        capture_output=True,
    )


_SUPERTONIC_TTS = None  # lazy module-level singleton to amortize ~260MB model load


def _synthesize_supertonic(text: str, out_path: Path) -> None:
    """Open-source Supertonic neural TTS → 44.1 kHz WAV.

    Uses the `supertonic` pip package; auto-downloads its ONNX models from
    Hugging Face on first use (~260 MB cached). No API key, no internet
    after that. Voice picked by SUPERTONIC_VOICE env var (default ``M4``);
    language by SUPERTONIC_LANG (default ``en``).
    """
    try:
        from supertonic import TTS  # type: ignore  # noqa: I001
    except ImportError as e:
        raise RuntimeError(
            "supertonic not installed. Install with one of:\n"
            "  uv add supertonic                      (adds to this project's venv)\n"
            "  pipx install supertonic                (isolated global)\n"
            "  pip install supertonic                 (any venv)\n"
            "First run will auto-download ~260 MB of ONNX models from Hugging "
            "Face into your local HF cache; subsequent runs are fully offline.\n"
            f"(original error: {e})"
        )
    global _SUPERTONIC_TTS
    if _SUPERTONIC_TTS is None:
        # auto_download=True fetches the models on first instantiation; after
        # that they're cached, so subsequent slides in the same process reuse
        # the in-memory model (which is the slow part to load).
        _SUPERTONIC_TTS = TTS(auto_download=True)

    voice_name = os.environ.get("SUPERTONIC_VOICE", "M4")
    lang = os.environ.get("SUPERTONIC_LANG", "en")
    try:
        style = _SUPERTONIC_TTS.get_voice_style(voice_name=voice_name)
    except Exception as e:
        raise RuntimeError(
            f"Supertonic voice {voice_name!r} not found ({e}). "
            f"Try SUPERTONIC_VOICE=M1, M2, M3, M4, F1, F2, … (see "
            f"https://huggingface.co/Supertone/supertonic-3 for the full list)."
        )
    wav, _duration = _SUPERTONIC_TTS.synthesize(
        text=text, voice_style=style, lang=lang,
    )
    out_path = out_path.with_suffix(".wav")
    _SUPERTONIC_TTS.save_audio(wav, str(out_path))


def _synthesize_espeak(text: str, out_path: Path) -> None:
    """Lightweight eSpeak-NG fallback → WAV. Very robotic but works
    on every platform with no setup beyond `brew install espeak-ng`."""
    bin_name = "espeak-ng" if shutil.which("espeak-ng") else "espeak"
    if not shutil.which(bin_name):
        raise RuntimeError(
            "Neither `espeak-ng` nor `espeak` is on PATH. "
            "Install with `brew install espeak-ng` (macOS) or "
            "`apt-get install espeak-ng` (Linux)."
        )
    out_path = out_path.with_suffix(".wav")
    subprocess.run(
        [bin_name, "-w", str(out_path), text],
        check=True,
    )


def _synthesize(text: str, out_path_hint: Path) -> Path:
    """Dispatch to the configured TTS engine. Returns the actually-written
    path (the extension may differ from `out_path_hint` based on engine)."""
    engine = _resolve_tts_engine()
    if engine == "say":
        out = out_path_hint.with_suffix(".aiff")
        _synthesize_say(text, out)
        return out
    if engine == "piper":
        out = out_path_hint.with_suffix(".wav")
        _synthesize_piper(text, out)
        return out
    if engine == "supertonic":
        out = out_path_hint.with_suffix(".wav")
        _synthesize_supertonic(text, out)
        return out
    if engine == "espeak":
        out = out_path_hint.with_suffix(".wav")
        _synthesize_espeak(text, out)
        return out
    raise RuntimeError(f"unreachable: engine {engine!r}")


def auto_narrate(
    job_id: str,
    overwrite: bool = False,
    progress_cb=None,
) -> list[Path]:
    """Generate audio for the job with the configured TTS engine.

    Engine is picked by ``TTS_ENGINE`` env var: ``say`` (default macOS),
    ``piper`` (open-source neural TTS, much better quality), or
    ``espeak`` (lightweight cross-platform fallback). See module-level
    ``VALID_TTS_ENGINES``.

    Writes one ``slide_NN.<ext>`` per segment into ``jobs/<id>/audio/``.
    Extension depends on engine: .aiff for say, .wav for piper / espeak.

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

    engine = _resolve_tts_engine()
    if progress_cb:
        progress_cb(f"TTS engine: {engine}")

    written: list[Path] = []
    for i, seg in enumerate(segments):
        existing = find_audio_for_slide(audio_dir, i)
        if existing is not None and not overwrite:
            if progress_cb:
                progress_cb(f"slide {i + 1}: keeping existing {existing.name}")
            continue
        if existing is not None and overwrite:
            existing.unlink()
        # Pass a stem hint; _synthesize picks the extension per engine.
        out = _synthesize(seg.narration, audio_dir / f"slide_{i:02d}")
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
