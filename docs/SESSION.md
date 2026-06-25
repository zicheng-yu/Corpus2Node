# SESSION — 会话交接摘要

> 一轮会话结束时覆盖写这份（只留最新一轮），下一轮开始时先读这份做快速定位，再去 `docs/PROGRESS.md` 看全量真相与文件夹→功能映射。
> 这份是「30 秒看懂现状」；PROGRESS.md 是「完整账本」。

**最近更新**：2026-06-25 · 分支 `feat`

---

## 当前已验证

- 后端 **112 passed**（`.venv/bin/python -m pytest -q`，2026-06-25 实测）；`.venv/bin/ruff check src tests` clean。
- 前端 `npm run build` 通过（2026-06-25 实测）。
- 离线 workflow（ingest→extract→critic→build）+ 在线 chat/notes/exam/export 路由齐全且有测试。
- 本轮审阅问题已修复：API 安全开关、上传安全、原子写、chat 历史/引用闭环、notes/exam 参数冲突保护、workflow 统计一致、前端跳转/上传失败处理、启动脚本误杀端口风险、最小 CI。
- **未在 CI 覆盖**：真实 LLM 端到端（建图/问答/出题）与 eval baseline 数字——需用户凭据 + token。

## 本轮改动

- **API 安全**：新增 `APP_ENV` / `DEBUG_TRACEBACKS` / `CORS_ALLOW_ORIGINS` / `API_AUTH_TOKEN` / `MAX_UPLOAD_BYTES`；生产环境隐藏 traceback；配置 token 后非公开 API 需 Bearer token。
- **上传安全**：文件名清洗为 basename，磁盘按 `source_id + ext` 存储；分块读取、大小限制、空文件/超限拒绝，避免路径穿越与同名覆盖。
- **存储一致性**：artifact、LLM settings、prompt settings、workflow run、graph candidates/critic report 改同目录临时文件 + `os.replace` 原子写。
- **chat**：最近 12 条历史传给 agent；生成前预检索并提供可引用上下文；模型漏写引用编号时补 `参考来源`；流式失败不落盘空回答。
- **workflow / jobs**：流式 workflow 结束和缓存路径都回填真实 `chunk_count`；notes/exam 同 session 同参数复用任务，异参数并发返回 409。
- **前端**：命令面板按 session 状态跳 workspace/pipeline 并隐藏虚拟总图谱；上传全部失败不进入 pipeline；前端包名改 `corpus2node-frontend`。
- **CI / 脚本 / 文档**：新增 GitHub Actions 最小 CI；`corpus stop` 只停 pidfile 进程，新增 `corpus force-stop` 清端口；README 按要求清空；`.env.example` 和 `docs/PROGRESS.md` 已同步。
- **提交**：本轮修复已提交为最新 `fix: harden app flows after project review`。

## 仍损坏或未验证

- **eval baseline 数字还是空的**：harness 与指标就绪，但没跑过真实数据，§10「F1 X→Y / grounding 0→N%」叙事尚无真实数字。
- **全局概念搜索仍是子串匹配**：即时、零 token，但大库需索引；语义模糊搜索未做。
- README 当前故意为空，开发早期暂不维护对外说明。
- `AGENTS.md` 是 `CLAUDE.md` 的旧副本，已分叉 stale（两者均 gitignore）；尚未决定删除/做成指针/同步。

## 下一步最佳动作

1. 跑真实小语料记 eval baseline（需用户凭据）：`corpus dev` → 设置里绑凭据 → 建一个 session → `python -m corpus2node.eval <session> --default-gold`，把数字填进 PROGRESS「当前已验证状态」。
2. 之后再考虑 Step 7 工程化：`Course→Corpus` 契约重命名、持久化向量库、Docker。

**不要动**：
- wire 契约（`core/types.py` ↔ `frontend/src/types/index.ts`）——除非专门做 Course→Corpus 重命名，且两边同步改。
- `db/`、`workers/`、联网 search/synthesize 残留——按操作手册约定，不带走、不复活。
- 确定性图算法（`graph/build.py` 中心性/聚类/合并/共现边）的「交给 LLM」式改写。
