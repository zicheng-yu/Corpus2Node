# SESSION — 会话交接摘要

> 一轮会话结束时覆盖写这份（只留最新一轮），下一轮开始时先读这份做快速定位，再去 `docs/PROGRESS.md` 看全量真相与文件夹→功能映射。
> 这份是「30 秒看懂现状」；PROGRESS.md 是「完整账本」。

**最近更新**：2026-06-26 · 分支 `feat`

---

## 当前已验证

- 后端 **126 passed**（`.venv/bin/python -m pytest -q`，2026-06-26 实测）；`.venv/bin/ruff check src tests` clean。
- 前端 `npm run build` 通过（2026-06-26 实测）；`BridgeGraphView` 懒加载成独立 chunk，首页主包 376KB→229KB。
- 知识发现（用户基线）+ 本轮四向增强（桥接图可视化 / 可溯源跳转 / 质量 / 历史）均有测试或构建覆盖。
- **未在 CI 覆盖**：真实 LLM judge 质量、真实建图/问答/出题、eval baseline——都需用户凭据 + token。

## 本轮改动

- **流水线阶段卡片 5→4 一行（最新）**：`PipelinePage.tsx` 去掉「质检修复」卡片（critic 仍在后端跑，折叠进「构建图谱」，文案补说明），phase 重映射（critic→3、done→4）；CSS 本就 `repeat(4,1fr)` 无需改；run-metrics 面板仍单列 critic。`npm run build` 通过。

### 上一阶段：知识发现增强（已提交 `3b096e9`）

- **`discovery/engine.py`（质量）**：8 类 `RELATION_TYPES` 枚举 + judge 输出回填（中文别名/越界→shared_context）；证据每侧 top-2 交错；结构化信号（共享图谱邻居/标签，`_neighbor_index`/`_struct_terms`）并入评分；大候选池（>12）分批 `asyncio.gather` 并发 judge 并按 confidence 合并；算法版 `relation_type`/`novelty` 重算。
- **`components/discovery/BridgeGraphView.tsx`（可视化，新文件）**：ReactFlow 三列 bridge graph（发现→知识点→资料集），概念节点可点击溯源；懒加载。
- **`HomePage.tsx`（跳转 + 历史）**：卡片概念 chip / 证据块、桥接图概念节点点击 → `/session/{id}?concept=`；`DiscoveryHistoryBar` 历史面板（点开重载）；面板加桥接图开关 + 关闭。
- **`storage/local.py`**：`list_discovery_reports` 改按 `generated_at` 倒序。
- **`tests/test_discovery.py`**：+3 例（枚举回填 / 分批合并 / 多 chunk 证据），共 9 例。

## 仍损坏或未验证

- 知识发现已由用户提交为 `3b096e9`；本轮流水线改动将随本次一并提交。
- 算法版关系类型 / novelty 是启发式；真实 judge 质量需用户凭据实测。
- `listDiscoveries()` 拉全量报告（含 bridge graph），库很大时宜加 summary 端点。
- 证据 blockquote 点击未做键盘可达（概念 chip 是 `<button>` 已可达）。
- eval baseline 数字仍空；全局概念搜索仍是子串匹配；README 故意为空；`AGENTS.md` 仍是 stale 副本。

## 下一步最佳动作

1. 浏览器里 `corpus dev` 确认流水线四阶段一行、知识发现桥接图/跳转/历史观感。
2. 之后回到 eval baseline / Step 7 工程化。

**不要动**：
- wire 契约（`core/types.py` ↔ `frontend/src/types/index.ts`）——除非专门做 Course→Corpus 重命名且两边同步。
- `db/`、`workers/`、联网 search/synthesize 残留——不带走、不复活。
- 确定性图算法（`graph/build.py`）与发现的确定性候选/评分「交给 LLM」式改写——judge 只做裁剪/命名，不接管图算法。
