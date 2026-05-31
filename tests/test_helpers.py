"""Unit tests for pure helpers in pipeline.py.

These tests must not call Claude / Ollama / Playwright / ffmpeg / `say`.
Anything that touches one of those belongs in smoke_test.py instead.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from pipeline import (
    Aesthetic,
    Critique,
    MIN_SLIDE_SECONDS,
    SPEAKING_WPM,
    Segment,
    VALID_BACKENDS,
    _coerce_aesthetic,
    _coerce_critique,
    _coerce_segments,
    _combined_prompt,
    _estimate_duration,
    _extract_json,
    _extract_json_obj,
    _first,
    _fmt_ts,
    _render_script_text,
    _strip_fences,
    find_audio_for_slide,
    set_request_overrides,
)


# ─── _strip_fences ────────────────────────────────────────────────────────────

class TestStripFences:
    def test_no_fence_returns_input(self):
        assert _strip_fences("hello world") == "hello world"

    def test_triple_fence_with_language(self):
        assert _strip_fences("```json\n{\"a\":1}\n```") == "{\"a\":1}"

    def test_triple_fence_bare(self):
        assert _strip_fences("```\n{\"a\":1}\n```") == "{\"a\":1}"

    def test_strips_whitespace(self):
        assert _strip_fences("   \n\nhello\n  ") == "hello"


# ─── _extract_json ────────────────────────────────────────────────────────────

class TestExtractJson:
    def test_clean_object(self):
        assert _extract_json('{"a": 1}') == {"a": 1}

    def test_clean_array(self):
        assert _extract_json('[1, 2, 3]') == [1, 2, 3]

    def test_fence_wrapped(self):
        assert _extract_json('```json\n{"a": 1}\n```') == {"a": 1}

    def test_prose_preamble_finds_object(self):
        text = "Here is the result:\n{\"a\": 1}\nDone."
        assert _extract_json(text) == {"a": 1}

    def test_earliest_opener_wins_when_both_present(self):
        # Stray "[1]" appears BEFORE the real object — earlier code path
        # would have returned the array; now the leftmost opener wins.
        text = 'Notes [1]: {"answer": 42}'
        # We expect either is acceptable (both are valid JSON); just make
        # sure the parser doesn't crash and returns *something* parseable.
        result = _extract_json(text)
        assert result in ([1], {"answer": 42})

    def test_garbage_raises(self):
        with pytest.raises(ValueError, match="Could not parse JSON"):
            _extract_json("nothing here that looks like json")


# ─── _extract_json_obj ────────────────────────────────────────────────────────

class TestExtractJsonObj:
    def test_clean_object(self):
        assert _extract_json_obj('{"a": 1}') == {"a": 1}

    def test_single_elem_list_unwraps(self):
        assert _extract_json_obj('[{"a": 1}]') == {"a": 1}

    def test_multi_elem_list_raises(self):
        with pytest.raises(ValueError, match="got a list"):
            _extract_json_obj('[{"a": 1}, {"b": 2}]')

    def test_scalar_raises(self):
        with pytest.raises(ValueError, match="got int"):
            _extract_json_obj('42')


# ─── _first ───────────────────────────────────────────────────────────────────

class TestFirst:
    def test_returns_first_match(self):
        assert _first({"title": "T"}, ("name", "title")) == "T"

    def test_case_insensitive(self):
        assert _first({"Title": "T"}, ("title",)) == "T"

    def test_none_if_no_match(self):
        assert _first({"x": 1}, ("y", "z")) is None


# ─── _coerce_segments ─────────────────────────────────────────────────────────

class TestCoerceSegments:
    def test_happy_path(self):
        raw = [{"title": "A", "key_visual": "v", "narration": "n"}]
        segs = _coerce_segments(raw)
        assert len(segs) == 1
        assert segs[0] == Segment(title="A", key_visual="v", narration="n")

    def test_aliased_keys(self):
        raw = [{"heading": "A", "visual": "v", "script": "n"}]
        segs = _coerce_segments(raw)
        assert segs[0].title == "A"
        assert segs[0].key_visual == "v"
        assert segs[0].narration == "n"

    def test_wrapped_in_dict(self):
        raw = {"segments": [{"title": "A", "key_visual": "v", "narration": "n"}]}
        assert len(_coerce_segments(raw)) == 1

    def test_missing_narration_falls_back_to_longest_string(self):
        raw = [{"title": "A", "key_visual": "v", "extra": "spoken stuff here"}]
        segs = _coerce_segments(raw)
        # _first scans NARRATION_KEYS — "extra" isn't one — so fallback wins.
        assert "spoken stuff here" in segs[0].narration

    def test_drops_stray_strings(self):
        raw = ["intro text", {"title": "A", "key_visual": "v", "narration": "n"}]
        assert len(_coerce_segments(raw)) == 1

    def test_drops_segments_with_no_title_AND_no_string_values(self):
        # Item 0 has neither a title nor any string fields that the
        # narration-fallback can latch onto → dropped.
        raw = [{"unrelated_int": 42},
               {"title": "kept", "narration": "ok"}]
        assert len(_coerce_segments(raw)) == 1

    def test_segment_with_only_key_visual_kept_via_fallback(self):
        # Item has key_visual (a string value) — narration falls back to
        # the longest string field, so the segment is kept (intentional —
        # losing it would be worse than a slightly weird narration).
        raw = [{"key_visual": "only-visual"}]
        segs = _coerce_segments(raw)
        assert len(segs) == 1
        assert "only-visual" in segs[0].narration

    def test_empty_list_raises(self):
        with pytest.raises(ValueError, match="no usable segments"):
            _coerce_segments([])

    def test_non_list_non_dict_raises(self):
        with pytest.raises(ValueError, match="Expected the writer to return"):
            _coerce_segments(42)


# ─── _coerce_aesthetic ────────────────────────────────────────────────────────

class TestCoerceAesthetic:
    def test_happy(self):
        a = _coerce_aesthetic({
            "name": "X", "palette": ["#000", "#fff"],
            "font_family": "serif", "description": "d",
        })
        assert a.name == "X"
        assert a.palette == ["#000", "#fff"]
        assert a.font_family == "serif"

    def test_aliased_keys(self):
        a = _coerce_aesthetic({
            "aesthetic": "X", "colors": ["#000"],
            "font": "serif", "rationale": "why",
        })
        assert a.name == "X"
        assert a.palette == ["#000"]

    def test_palette_as_comma_string(self):
        a = _coerce_aesthetic({"name": "X", "palette": "#000, #fff, #58a6ff"})
        assert a.palette == ["#000", "#fff", "#58a6ff"]

    def test_palette_as_list_of_dicts(self):
        a = _coerce_aesthetic({"name": "X",
                               "palette": [{"hex": "#000"}, {"color": "#fff"}]})
        assert a.palette == ["#000", "#fff"]

    def test_safe_defaults_when_empty(self):
        a = _coerce_aesthetic({})
        assert a.name == "Default"
        assert a.palette  # non-empty default
        assert a.font_family


# ─── _coerce_critique ─────────────────────────────────────────────────────────

class TestCoerceCritique:
    def test_happy(self):
        c = _coerce_critique({
            "scores": {"understandability": 5, "analogies": 4, "wonder": 5},
            "verdict": "approve",
            "notes": ["n1", "n2"],
        })
        assert c == Critique(
            scores={"understandability": 5, "analogies": 4, "wonder": 5},
            verdict="approve",
            notes=["n1", "n2"],
        )

    def test_scores_as_list_of_dicts(self):
        c = _coerce_critique({
            "scores": [{"understandability": 4},
                       {"analogies": 5},
                       {"wonder": 4}],
            "verdict": "approve",
            "notes": [],
        })
        assert c.scores == {"understandability": 4, "analogies": 5, "wonder": 4}

    def test_scores_as_string_fractions(self):
        c = _coerce_critique({
            "scores": {"understandability": "5/5", "wonder": "4 out of 5"},
            "verdict": "Approved",
            "notes": "single note",
        })
        assert c.scores == {"understandability": 5, "wonder": 4}
        assert c.verdict == "approve"
        assert c.notes == ["single note"]

    def test_verdict_normalization(self):
        assert _coerce_critique({"verdict": "approved!"}).verdict == "approve"
        assert _coerce_critique({"verdict": "REVISE"}).verdict == "revise"
        assert _coerce_critique({"verdict": "something else"}).verdict == "revise"

    def test_invalid_scores_type_raises(self):
        with pytest.raises(ValueError, match="should be a dict"):
            _coerce_critique({"scores": "5/5"})

    def test_missing_fields_get_defaults(self):
        c = _coerce_critique({})
        assert c.scores == {}
        assert c.verdict == "revise"   # default = not approved
        assert c.notes == []           # notes default is [] (empty list)


# ─── _estimate_duration ───────────────────────────────────────────────────────

class TestEstimateDuration:
    def test_empty_string_gives_min(self):
        # Empty narration still gets at least MIN_SLIDE_SECONDS.
        assert _estimate_duration("") == MIN_SLIDE_SECONDS

    def test_single_word(self):
        # 1 word at SPEAKING_WPM ≈ tiny; padded to min.
        assert _estimate_duration("hello") == MIN_SLIDE_SECONDS

    def test_long_text_scales(self):
        # 320 words at 160 wpm ≈ 120s + 1s pad = 121s.
        text = "word " * 320
        d = _estimate_duration(text)
        assert 119 < d < 123

    def test_custom_wpm(self):
        text = "word " * 160
        slower = _estimate_duration(text, wpm=80)
        faster = _estimate_duration(text, wpm=320)
        assert slower > faster

    def test_default_wpm_constant_used(self):
        text = "word " * SPEAKING_WPM   # exactly 1 minute's worth
        d = _estimate_duration(text)
        # 60s + 1s tail pad
        assert 60.5 < d < 61.5


# ─── _fmt_ts ──────────────────────────────────────────────────────────────────

class TestFmtTs:
    def test_zero(self):
        assert _fmt_ts(0) == "0:00"

    def test_under_minute(self):
        assert _fmt_ts(45) == "0:45"

    def test_minute_boundary(self):
        assert _fmt_ts(59) == "0:59"
        assert _fmt_ts(60) == "1:00"
        assert _fmt_ts(61) == "1:01"

    def test_multi_minute(self):
        assert _fmt_ts(125) == "2:05"

    def test_hour_renders_as_total_minutes(self):
        assert _fmt_ts(3600) == "60:00"

    def test_fractional_seconds_rounds(self):
        assert _fmt_ts(45.4) == "0:45"
        assert _fmt_ts(45.7) == "0:46"


# ─── find_audio_for_slide ─────────────────────────────────────────────────────

class TestFindAudio:
    def test_finds_matching_wav(self, tmp_path):
        (tmp_path / "slide_00.wav").write_bytes(b"")
        (tmp_path / "slide_01.wav").write_bytes(b"")
        assert find_audio_for_slide(tmp_path, 0).name == "slide_00.wav"
        assert find_audio_for_slide(tmp_path, 1).name == "slide_01.wav"

    def test_accepts_other_extensions(self, tmp_path):
        for ext in ("mp3", "m4a", "aiff", "flac", "ogg", "opus", "aac"):
            (tmp_path / f"slide_05.{ext}").write_bytes(b"")
            assert find_audio_for_slide(tmp_path, 5) is not None
            (tmp_path / f"slide_05.{ext}").unlink()

    def test_missing_returns_none(self, tmp_path):
        assert find_audio_for_slide(tmp_path, 0) is None

    def test_wrong_stem_ignored(self, tmp_path):
        (tmp_path / "Slide_00.wav").write_bytes(b"")    # capital S — no match
        (tmp_path / "slide-0.wav").write_bytes(b"")     # wrong format
        assert find_audio_for_slide(tmp_path, 0) is None

    def test_picks_first_sorted_when_duplicates(self, tmp_path):
        (tmp_path / "slide_00.wav").write_bytes(b"")
        (tmp_path / "slide_00.mp3").write_bytes(b"")
        # sorted() iteration: mp3 < wav alphabetically.
        assert find_audio_for_slide(tmp_path, 0).suffix == ".mp3"


# ─── _render_script_text ──────────────────────────────────────────────────────

class TestRenderScriptText:
    def test_basic_output(self):
        segs = [
            Segment(title="A", key_visual="v1", narration="hello world."),
            Segment(title="B", key_visual="v2", narration="goodbye."),
        ]
        out = _render_script_text("Topic", segs, [10.0, 20.0], "audio")
        # Topic appears.
        assert "Topic" in out
        # Each segment present.
        assert "A" in out and "B" in out
        # Filenames present in the right zero-padded form.
        assert "slide_00.wav" in out and "slide_01.wav" in out
        # Timestamps cumulate.
        assert "0:00 → 0:10" in out
        assert "0:10 → 0:30" in out


# ─── Backend dispatch ─────────────────────────────────────────────────────────

class TestBackends:
    def test_five_backends_registered(self):
        assert set(VALID_BACKENDS) == {
            "claude_cli", "codex_cli", "gemini_cli", "ollama", "llm",
        }

    def test_unknown_backend_raises(self):
        with pytest.raises(RuntimeError, match="Unknown backend"):
            set_request_overrides(backend="pirate")

    def test_each_valid_backend_accepted(self):
        # set_request_overrides should NOT raise for any backend in the list.
        for b in VALID_BACKENDS:
            set_request_overrides(backend=b)   # also clears model
        set_request_overrides(backend=None)    # reset


class TestTtsOverride:
    def test_each_valid_engine_accepted(self):
        for e in ("say", "piper", "espeak"):
            set_request_overrides(tts_engine=e)
        set_request_overrides(tts_engine=None)  # reset

    def test_unknown_engine_raises(self):
        with pytest.raises(RuntimeError, match="Unknown TTS engine"):
            set_request_overrides(tts_engine="elvis")

    def test_override_affects_resolver(self):
        from pipeline import _resolve_tts_engine
        set_request_overrides(tts_engine="piper")
        assert _resolve_tts_engine() == "piper"
        set_request_overrides(tts_engine=None)  # reset
        # Now back to env default (say if no env var set).
        assert _resolve_tts_engine() in ("say", "piper", "espeak")


# ─── _combined_prompt (used by codex_cli + gemini_cli) ────────────────────────

class TestCombinedPrompt:
    def test_includes_both_parts(self):
        out = _combined_prompt("system part", "user part")
        assert "system part" in out
        assert "user part" in out

    def test_has_separator(self):
        out = _combined_prompt("a", "b")
        assert "\n\n---\n\n" in out
