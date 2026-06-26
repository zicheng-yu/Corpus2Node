# SESSION — 会话交接摘要

> 一轮会话结束时覆盖写这份（只留最新一轮），下一轮开始时先读这份做快速定位，再去 `docs/PROGRESS.md` 看全量真相与文件夹→功能映射。
> 这份是「30 秒看懂现状」；PROGRESS.md 是「完整账本」。

**最近更新**：2026-06-26 · 分支 `feat`

---

## 当前已验证

- 后端 **127 passed**（`.venv/bin/python -m pytest -q`，2026-06-26）；`ruff check src tests` clean；前端 `npm run build` 通过。
- **音频摄入已修复并本机实测**：合成 WAV 端到端跑通 faster-whisper（CTranslate2+PyAV+onnxruntime，3.1s）。
- 离线 workflow + 在线 chat/notes/exam/export + 知识发现（桥接图/溯源/历史）均有测试或构建覆盖。
- **未在 CI 覆盖**：真实 LLM 端到端、真实音频转写质量、eval baseline——需用户凭据/token 或真实文件。

## 本轮改动（音频摄入修复）

- **根因**：Kimi/Moonshot **平台 API 不接受音频**（只 text/image/video；官方文档查证）。`Kimi-Audio` 是需自托管的开源模型，不在平台 API。所以音频没有云端路径，必须本地转写——用户「Kimi 能处理音频」是把消费端语音/开源模型当成了平台 API。
- **修复**：`faster-whisper` 从 `[audio]` extra **升为 core 依赖**（torch-free，与 docx/pptx/yaml 同级），删 `audio` extra；`uv sync` 装好；`audio_whisper.py` 文档+报错改为「本地转写 / Kimi 无音频 / `uv sync` 即可」。
- **测试**：`tests/test_adapters.py` 把仅在「未装 whisper」才跑的 skip 测试改成两条实测——依赖已 bundle + 缺失时报错清晰（monkeypatch 强制 ImportError）。

## 仍损坏或未验证

- core 安装体积略增（ctranslate2/av/onnxruntime，**无 torch**）；whisper 首次转写下载 `base` 模型(~140MB)。
- 若想要**云端 ASR**：当前 DeepSeek/Kimi 都不转写，需用户另加一个支持 `/audio/transcriptions` 的 OpenAI-compatible 凭据；本轮未建该路径（无可用凭据、避免投机），可按需再做。
- 算法版知识发现关系/novelty 是启发式，真实 judge 质量需用户凭据实测。
- eval baseline 数字仍空；全局概念搜索仍是子串匹配；README 故意为空；`AGENTS.md` 仍是 stale 副本。

## 下一步最佳动作

1. 用真实音频建一次图，确认转写质量（首次会下 `base` 模型）。
2. 如确实想要云端 ASR，再决定加哪个可转写凭据 + 一个 `index`/`ingest` 层的 OpenAI-compatible 转写 seam。
3. 之后回到 eval baseline / Step 7 工程化。

**不要动**：
- wire 契约（`core/types.py` ↔ `frontend/src/types/index.ts`）——除非专门做 Course→Corpus 重命名且两边同步。
- `db/`、`workers/`、联网 search/synthesize 残留——不带走、不复活。
- 试图把音频塞进 Kimi `video_url`/拼假视频绕过——平台 API 不接受音频，是约束不是 bug。
