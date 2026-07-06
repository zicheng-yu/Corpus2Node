# SESSION — 会话交接摘要

> 一轮会话结束时覆盖写这份（只留最新一轮），下一轮开始时先读这份做快速定位，再去 `docs/PROGRESS.md` 看全量真相与文件夹→功能映射。
> 这份是「30 秒看懂现状」；PROGRESS.md 是「完整账本」。

**最近更新**：2026-07-06 · 分支 `feat`

---

## 本轮做了什么（全离线 LLM 方案）

- 注册表新增本地 provider kind：`ollama`（原生 ChatOllama，`num_ctx` 默认 8192、`reasoning=False`）与 `lmstudio`（OpenAI 兼容 + dummy key）；凭据可设 `num_ctx`/`max_concurrency`；`concurrency_for` 接入 extract/critic。
- Embedding：`embedding` 用途绑 ollama → `OllamaEmbeddings`；其它自定义端点 `OpenAIEmbeddings` 自动关 `check_embedding_ctx_length`。
- 摄入离线化：`pdf_local.py`（pypdf）、`vision_is_moonshot()` 门控 Kimi 专属、视频非 Kimi 回退 whisper 音轨转写。
- 抽取确定性修复：`_reconcile_relation_endpoints` 端点别名归一（修「小模型关系端点悬空被 critic 全丢」，云端同益）。
- 新端点 `POST /settings/llm/models`（枚举本地/远端模型）；SettingsPanel 支持本地 kind（预填端点、免密钥、一键读模型、num_ctx/并发）。
- 本机 E2E（M3/24GB，Ollama 升到 0.31.1，`gemma4:e2b-it-qat`+`bge-m3`，隔离存储）：workflow/chat/exam 全过；速度实测 no-think ~5×、temp 0.2 抑方差、extract c4/c1 = 1.6×。
- 验证：**pytest 153 passed** · ruff clean · tsc + vite build ✅。依赖 += `langchain-ollama`、`pypdf`。

## 仍需注意

- **上一轮 critic 修复（grounding 字面证据优先 + 近清空保护）仍未提交**：`graph/critic.py` + `tests/test_critic.py` 是工作区未提交改动，本轮提交刻意未包含它们。
- gemma4 判卷（GraphCriticReport）偶尔过不了 schema 校验 → judge verdicts 为空，仅确定性修复兜底；`llama3.1:8b` 判卷更稳。
- 离线建库建议把 graph/critic/exam 绑定的 temperature 设为 0.2（绑定 UI 暂未暴露该字段，可经 API 或换绑时补）。
- 本机 `ollama serve` 由本轮以 `OLLAMA_NUM_PARALLEL=4` 手动拉起；用 Ollama.app 重启后走它自己的默认值。
- LM Studio 本机未安装：lmstudio kind 与 openai 同一 ChatOpenAI 路径、已单测；装好后在设置面板加凭据冒烟即可。

## 下一步最佳动作

1. 浏览器实测：设置 → 模型 → 新增「Ollama（本地）」凭据（一键读模型列表）→ 绑全用途 → 建一个离线库走一遍。
2. 决定是否提交上一轮的 critic 修复（当前仍在工作区）。
3. （可选）装 LM Studio 后对 lmstudio kind 做一次真机冒烟。
