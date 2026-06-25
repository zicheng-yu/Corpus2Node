# SESSION — 会话交接摘要

> 一轮会话**结束时覆盖写**这份（只留最新一轮），下一轮**开始时先读**这份做快速定位，再去 `docs/PROGRESS.md` 看全量真相与文件夹→功能映射。
> 这份是「30 秒看懂现状」；PROGRESS.md 是「完整账本」。

**最近更新**：2026-06-25 · 分支 `feat`

---

## 当前已验证

- 后端 **105 passed**（`.venv/bin/python -m pytest -q`，2026-06-25 实测）；ruff clean；工作树干净。
- 前端 `npm run build` 在 commit `2a96b60` 通过；此后只动了 `docs/` + `CLAUDE.md`，未碰前端。
- 离线 workflow（ingest→extract→critic→build）+ 在线 chat/notes/exam/export 路由齐全且有测试。
- **未在 CI 覆盖**：真实 LLM 端到端（建图/问答/出题）与 eval baseline 数字——需用户凭据 + token。

## 本轮改动

- **全局知识点搜索**：新增 `GET /graph/concepts`（跨所有已建图谱子串搜概念，按 importance 排序），接入 ⌘K 命令面板 + 首页工具栏；命中跳 `?concept=` 聚焦。
- **知识库折叠**：首页分组头点击折叠，状态存 localStorage。
- **小改**：SettingsPanel 提示词首项标签 →「全局」。
- **harness（本轮重点）**：建 `docs/PROGRESS.md`（进度真相 + 文件夹→功能映射 + 会话记录）与本文件；`CLAUDE.md` §1 巨型进度段落瘦身为指向 PROGRESS 的指针、§9 完成态注解收成一行。
- 提交：`36c995b`、`2a96b60`（功能）；docs harness + CLAUDE 瘦身 = 本 docs 提交。

## 仍损坏或未验证

- **全局概念搜索是子串匹配**：即时、零 token，但大库需索引；语义模糊搜索未做。
- **eval baseline 数字还是空的**：harness 与指标就绪，但没跑过真实数据，§10「F1 X→Y / grounding 0→N%」叙事尚无真实数字。
- `corpus start` 后立刻 curl 偶尔抢跑 boot 返空——启动脚本时序，非代码 bug；以 `.run/logs/backend.log` 为准。
- `AGENTS.md` 是 `CLAUDE.md` 的旧副本，已分叉 stale（两者均 gitignore）；尚未决定删除/做成指针/同步。

## 下一步最佳动作

1. **跑真实小语料记 eval baseline**（最高优先，需用户凭据）：`corpus dev` → 设置里绑凭据 → 建一个 session → `python -m corpus2node.eval <session> --default-gold`，把数字填进 PROGRESS「当前已验证状态」。
2. 之后再考虑 Step 7 工程化（`Course→Corpus` 契约重命名、持久化向量库、Docker、README）。

**不要动**：
- wire 契约（`core/types.py` ↔ `frontend/src/types/index.ts`）——除非专门做 Course→Corpus 重命名，且两边同步改。
- `db/`、`workers/`、联网 search/synthesize 残留——按 CLAUDE.md §8，不带走、不复活。
- 确定性图算法（`graph/build.py` 中心性/聚类/合并/共现边）的「交给 LLM」式改写——违反 CLAUDE.md §2 核心原则。
