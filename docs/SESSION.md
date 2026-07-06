# SESSION — 会话交接摘要

> 一轮会话结束时覆盖写这份（只留最新一轮），下一轮开始时先读这份做快速定位，再去 `docs/PROGRESS.md` 看全量真相与文件夹→功能映射。
> 这份是「30 秒看懂现状」；PROGRESS.md 是「完整账本」。

**最近更新**：2026-07-06 (2) · 分支 `feat`

---

## 本轮做了什么

1. **工作区清零**：上轮遗留全部入库——critic grounding 修复（`20ebc2a`）、Docker 生产栈 deploy/（`96d39b1`）、docs（`ed2394d`）。
2. **`docs/DEPLOYMENT_MODELS.md`**：生产开源模型推荐（三档：单模型全包 Qwen3-VL-32B / 甜点 Qwen3.5-35B-A3B / 旗舰 DeepSeek-V4-Flash；vLLM 部署参数、注册表绑定表、显存速查；扫描 PDF OCR 局限已注明）。
3. **知识发现 v2「跨库创新提案」**（老板看各部门汇报找创新的场景）：
   - 后端：findings 之上加 proposer 层（Purpose.chat→critic，fallback 模板成案）；`InnovationProposal` 契约；意图 intent 贯穿；采纳/搁置 PATCH 持久化 + 历史避重；深挖 POST 出五字段最小方案。
   - 前端：发现统一弹窗（含意图输入）；提案卡（采纳/搁置/深挖）优先于 finding 卡；**呈现图重做**：部门→桥接概念→提案 三列（旧报告自动保留旧布局）。
   - 本机 gemma4 离线实测：39s 产 4 条全跨集 LLM 提案，deepen 6.6s 成案。

## 关键教训（别再踩）

- **json_mode 必须在 prompt 里给字段形状示例**（服务端不锁 schema）；新加结构化调用先抄 `_PROPOSAL_FORMAT_HINT` 的做法。
- 小模型引用概念名会带显示后缀/中英括号变体 → grounding 一律多键（raw+去括号）+ 一键多参与者 + 优先未覆盖资料集。

## 仍需注意

- 本机 `ollama serve` 是手动 `OLLAMA_NUM_PARALLEL=4` 拉起的；Ollama.app 重启后用它自己的默认值。
- 离线建库建议 graph/critic/exam 绑定 temperature=0.2（绑定 UI 未暴露该字段，走 API）。
- LM Studio 本机未装（代码路径同 openai kind，已单测）。

## 下一步最佳动作

1. 浏览器实测：选 2+ 资料集 → 知识发现（填意图）→ 检查提案卡交互、图上点提案定位、采纳后刷新仍在。
2. 真实多领域语料（非同一讲义的两次构建）跑一次提案质量评估。
3. 可选：深挖流式化；把 per-binding temperature 暴露到设置面板。
