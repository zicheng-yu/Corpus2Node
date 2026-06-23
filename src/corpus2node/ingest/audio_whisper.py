"""Audio ingestion via faster-whisper (local ASR): audio -> transcript text.

faster-whisper uses CTranslate2 + PyAV (bundled ffmpeg) — no torch, no separate
ffmpeg binary. Install with `uv sync --extra audio`. The model downloads from
Hugging Face on first use.
"""
from __future__ import annotations

import logging

from corpus2node.config import settings

logger = logging.getLogger(__name__)

_MODEL_CACHE: dict[tuple[str, str], object] = {}


def transcribe_audio(filename: str, path: str) -> list[str]:
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise RuntimeError("Audio ingestion needs faster-whisper — run `uv sync --extra audio`.") from exc

    cache_key = (settings.whisper_model_size, "int8")
    model = _MODEL_CACHE.get(cache_key)
    if model is None:
        logger.info("loading faster-whisper model %s", settings.whisper_model_size)
        model = WhisperModel(settings.whisper_model_size, device="auto", compute_type="int8")
        _MODEL_CACHE[cache_key] = model

    language = None if settings.whisper_language == "auto" else settings.whisper_language
    segments, _info = model.transcribe(path, language=language, vad_filter=True, beam_size=5)
    texts = [segment.text.strip() for segment in segments if segment.text.strip()]
    if not texts:
        raise RuntimeError(f"No speech could be transcribed from {filename}.")
    return [" ".join(texts)]
