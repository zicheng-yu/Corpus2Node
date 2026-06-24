"""Video ingestion via Kimi K2.6 (multimodal): video -> descriptive text.

Kimi accepts a base64 data URL via the OpenAI-compatible ``video_url`` content type.
Keep resolution <= FHD (1920x1080); token cost scales with keyframes/resolution.
Like the image path, K2.6 thinking is disabled via extra_body and no temperature/
top_p is set. Videos are large, so a longer timeout than the image path is used.
"""
from __future__ import annotations

import base64
from pathlib import Path

from corpus2node.config import settings

_VIDEO_PROMPT = (
    "请观看这段视频，把其中讲解的关键内容、出现的文字、公式、图表、步骤与结论尽量完整地转写并描述出来，"
    "用于构建学习知识库。按时间顺序组织，只输出内容本身，不要寒暄或解释你在做什么。"
)
# extension -> MIME subtype Kimi accepts (video/<subtype>)
_MIME = {
    ".mp4": "mp4", ".mpeg": "mpeg", ".mpg": "mpg", ".mov": "mov", ".avi": "avi",
    ".flv": "x-flv", ".webm": "webm", ".wmv": "wmv", ".3gp": "3gpp", ".3gpp": "3gpp",
}


def video_configured() -> bool:
    return bool(settings.kimi_api_key and settings.kimi_model)


def describe_video(filename: str, path: str) -> list[str]:
    if not video_configured():
        raise RuntimeError("Video ingestion needs Kimi configured (KIMI_API_KEY / KIMI_MODEL).")
    try:
        from openai import OpenAI
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("Video ingestion needs the `openai` package.") from exc

    mime = _MIME.get(Path(filename).suffix.lower(), "mp4")
    encoded = base64.b64encode(Path(path).read_bytes()).decode("ascii")
    data_url = f"data:video/{mime};base64,{encoded}"

    client_kwargs: dict[str, object] = {
        "api_key": settings.kimi_api_key,
        "timeout": max(settings.kimi_timeout_seconds, 180.0),  # video decoding is slow
    }
    if settings.kimi_base_url:
        client_kwargs["base_url"] = settings.kimi_base_url
    client = OpenAI(**client_kwargs)

    completion = client.chat.completions.create(
        model=settings.kimi_model,
        messages=[
            {"role": "system", "content": "你是 Kimi。"},
            {
                "role": "user",
                "content": [
                    {"type": "video_url", "video_url": {"url": data_url}},
                    {"type": "text", "text": _VIDEO_PROMPT},
                ],
            },
        ],
        extra_body={"thinking": {"type": "disabled"}},  # faster; K2.6 thinking is on by default
        # NOTE: K2.6 rejects custom temperature/top_p — do not set them.
    )
    text = (completion.choices[0].message.content or "").strip()
    return [text] if text else []
