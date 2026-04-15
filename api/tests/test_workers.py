"""Tests des handlers Celery — logique métier pure, sans DB ni broker."""

import pytest

from app.workers.tasks import _dispatch, _handle_text_analysis

# ── _handle_text_analysis ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_text_analysis_basic():
    result = await _handle_text_analysis({"text": "Bonjour le monde. Ceci est un test."})
    assert result["word_count"] == 7  # split() garde la ponctuation attachée au mot
    assert result["char_count"] > 0
    assert result["sentence_count"] >= 1
    assert "word_frequency" in result
    assert "preview" in result


@pytest.mark.asyncio
async def test_text_analysis_word_frequency():
    result = await _handle_text_analysis({"text": "chat chat chien chat chien"})
    freq = result["word_frequency"]
    assert freq["chat"] == 3
    assert freq["chien"] == 2


@pytest.mark.asyncio
async def test_text_analysis_preview_truncated():
    long_text = "a " * 100  # 200 chars
    result = await _handle_text_analysis({"text": long_text})
    assert result["preview"].endswith("…")
    assert len(result["preview"]) <= 123  # 120 chars + "…"


@pytest.mark.asyncio
async def test_text_analysis_short_text_no_ellipsis():
    result = await _handle_text_analysis({"text": "Court"})
    assert not result["preview"].endswith("…")


@pytest.mark.asyncio
async def test_text_analysis_missing_text_raises():
    with pytest.raises(ValueError, match="text"):
        await _handle_text_analysis({})


@pytest.mark.asyncio
async def test_text_analysis_empty_text_raises():
    with pytest.raises(ValueError, match="text"):
        await _handle_text_analysis({"text": ""})


@pytest.mark.asyncio
async def test_text_analysis_top_10_words():
    """word_frequency contient au maximum 10 mots."""
    text = " ".join([f"mot{i}" for i in range(20)])
    result = await _handle_text_analysis({"text": text})
    assert len(result["word_frequency"]) <= 10


# ── _dispatch ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_dispatch_text_analysis():
    result = await _dispatch("text_analysis", {"text": "Hello world"})
    assert "word_count" in result


@pytest.mark.asyncio
async def test_dispatch_unknown_type_returns_neutral():
    """Un type inconnu ne lève pas d'exception — retourne une réponse neutre."""
    result = await _dispatch("type_inconnu", {"data": 42})
    assert result["task_type"] == "type_inconnu"
    assert result["status"] == "processed"
    assert result["payload"] == {"data": 42}


@pytest.mark.asyncio
async def test_dispatch_preserves_payload_for_unknown():
    payload = {"key": "value", "nested": {"a": 1}}
    result = await _dispatch("unknown_type", payload)
    assert result["payload"] == payload
