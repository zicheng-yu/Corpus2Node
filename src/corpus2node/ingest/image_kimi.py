"""Image ingestion via Kimi K2.6 vision (multimodal): image -> descriptive text.

Kimi only accepts base64 data URLs (not remote URLs). K2.6 defaults to thinking
mode and rejects a custom temperature/top_p, so we disable thinking via extra_body
and set no sampling params.
"""
from __future__ import annotations

import base64
from pathlib import Path

from corpus2node.ingest.kimi_client import vision_client, vision_is_moonshot

_VISION_PROMPT = (
    "请把这张图片中的所有文字、公式、图表、结构与关系尽量完整地转写并描述出来，"
    "用于构建学习知识库。只输出内容本身，不要寒暄或解释你在做什么。"
)
_MIME = {".png": "png", ".jpg": "jpeg", ".jpeg": "jpeg", ".webp": "webp", ".gif": "gif"}


def describe_image(filename: str, path: str) -> list[str]:
    client, model = vision_client()  # vision credential from the registry (Settings → Models)
    moonshot = vision_is_moonshot()

    mime = _MIME.get(Path(filename).suffix.lower(), "png")
    encoded = base64.b64encode(Path(path).read_bytes()).decode("ascii")
    data_url = f"data:image/{mime};base64,{encoded}"

    extra: dict = {}
    if moonshot:
        extra["extra_body"] = {"thinking": {"type": "disabled"}}  # faster; K2.6 thinking is on by default
        # NOTE: K2.6 rejects custom temperature/top_p — do not set them.
    completion = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": "你是 Kimi。" if moonshot else "你是资料转写助手。"},
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": data_url}},
                    {"type": "text", "text": _VISION_PROMPT},
                ],
            },
        ],
        **extra,
    )
    text = (completion.choices[0].message.content or "").strip()
    return [text] if text else []
