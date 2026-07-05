"""Video ingestion via Kimi K2.6 (multimodal): video -> descriptive text.

Videos are uploaded to Moonshot's Files API first and then referenced as
``ms://<file_id>`` in ``video_url``. Inline base64 is technically supported, but
it inflates payload size and is fragile for real lecture videos, especially when
traffic goes through a local proxy.
"""
from __future__ import annotations

import logging
from pathlib import Path

from corpus2node.config import settings
from corpus2node.ingest.kimi_client import vision_client, vision_is_moonshot

logger = logging.getLogger(__name__)

_VIDEO_PROMPT = (
    "请观看这段视频，把其中讲解的关键内容、出现的文字、公式、图表、步骤与结论尽量完整地转写并描述出来，"
    "用于构建学习知识库。按时间顺序组织，只输出内容本身，不要寒暄或解释你在做什么。"
)


def describe_video(filename: str, path: str) -> list[str]:
    if not vision_is_moonshot():
        # Fully-local fallback: no Moonshot Files API to upload to, so transcribe the
        # audio track instead (faster-whisper decodes video containers via PyAV).
        # Silent, visual-only videos won't yield text — bind vision to Kimi for those.
        from corpus2node.ingest.audio_whisper import transcribe_audio

        return transcribe_audio(filename, path)

    # video upload + decoding can be slow → a long timeout regardless of the binding default
    client, model = vision_client(timeout=max(settings.vision_timeout_seconds, 600.0))

    file_id: str | None = None
    try:
        with Path(path).open("rb") as handle:
            file_object = client.files.create(file=handle, purpose="video")
        file_id = file_object.id

        completion = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "你是 Kimi。"},
                {
                    "role": "user",
                    "content": [
                        {"type": "video_url", "video_url": {"url": f"ms://{file_id}"}},
                        {"type": "text", "text": _VIDEO_PROMPT},
                    ],
                },
            ],
            extra_body={"thinking": {"type": "disabled"}},  # faster; K2.6 thinking is on by default
            # NOTE: K2.6 rejects custom temperature/top_p — do not set them.
        )
        text = (completion.choices[0].message.content or "").strip()
        return [text] if text else []
    finally:
        if file_id:
            try:
                client.files.delete(file_id)
            except Exception as exc:  # pragma: no cover - best-effort remote cleanup
                logger.warning("failed to delete uploaded Kimi video file %s: %s", file_id, exc)
