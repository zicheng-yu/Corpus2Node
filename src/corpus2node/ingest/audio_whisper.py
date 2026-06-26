"""Audio ingestion via faster-whisper (local ASR): audio -> transcript text.

Audio is transcribed LOCALLY, not via Kimi: the Kimi/Moonshot platform API takes
text/image/video input but NOT audio, so there is no cloud path for .mp3/.wav/etc.
faster-whisper uses CTranslate2 + PyAV (bundled ffmpeg) — no torch, no separate
ffmpeg binary — and ships in the core dependencies. The model downloads from
Hugging Face on first use (default `base`, ~140MB, int8).
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
        raise RuntimeError(
            "Audio is transcribed locally with faster-whisper (the Kimi API does not "
            "accept audio). It ships in core deps — reinstall with `uv sync`."
        ) from exc

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
