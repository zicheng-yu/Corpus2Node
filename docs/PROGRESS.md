# PROGRESS — Corpus2Node 进度真相

> **这是项目进度的唯一真相（single source of truth）。**
> 每轮新会话**先读本文件**（再读 `docs/SESSION.md` 拿最新交接），每轮结束**往「会话记录」追加一条**并更新顶部状态。
> 架构决策 / 原则 / 约定看 `CLAUDE.md`（操作手册，相对稳定）；本文件只管「现在到哪了、东西在哪、下一步做什么」。
> 写入纪律：只写**已验证**的事实（跑过测试 / 见过产物）。没验证的写进「已知风险」，不要写进「已验证状态」。

---

## 当前已验证状态

- **后端测试 105 passed**（`.venv/bin/python -m pytest -q`，2026-06-25 实测，1.2s）。
- **前端 `npm run build` 通过**（最近一次在 commit `2a96b60` 状态；此后只改了 `docs/`，未动前端）。
- **ruff clean**。工作树干净，分支 `feat`。
- **离线闭环可跑**：上传 → workflow（ingest→extract→critic→build）→ GraphArtifact，离线 fixture e2e 通过；LLM 端到端（真实建图/问答/出题）**需用户用自己凭据在浏览器实测**（耗 token，CI 不覆盖）。
- **在线闭环可跑**：chat agent（强制引用 + trace + SSE）、notes（map-reduce + coverage critic）、exam（generator + verifier 回路）、export（md/tex/txt/pdf）路由齐全且有测试覆盖。
- **多模态摄入**：文档 7 类 + PDF（Kimi file-extract）+ 图片/视频（Kimi vision/K2.6）+ 音频（faster-whisper），注册表式接入。

## 仓库根目录

`/Users/zicheng/Documents/Projects/Corpus2Node`
Donor / 只读参考仓库：`/Users/zicheng/Documents/Playground/Course2Note`

## 标准启动路径

```bash
corpus dev      # 前台同时起前后端（调试用，Ctrl-C 停）；脚本 scripts/corpus.sh，alias 在 ~/.zshrc
corpus start     # 后台起，日志在 .run/logs/{backend,frontend}.log
corpus status    # 看进程/端口
corpus stop      # 停
# 后端单独：.venv/bin/uvicorn corpus2node.api.app:app --reload
# 前端单独：cd frontend && npm run dev
# 零构建验证 UI：后端起后访问 /ui（web/index.html，含凭据配置面板）
```
> 真实 LLM 跑通需先在「设置 → 模型」里登记凭据并按 purpose 绑定（graph/chat/critic/exam）。
> 已知：`corpus start` 后立刻 curl 偶尔抢跑 boot 返回空——是启动脚本的等待时序，不是代码 bug；以 `.run/logs/backend.log` 的 `Application startup complete` 为准。

## 标准验证路径

```bash
.venv/bin/python -m pytest -q                       # 后端全量（权威，与 uvicorn 同一 ASGI app）
.venv/bin/python -m pytest tests/test_graph_routes.py -q   # 单文件
cd frontend && npm run build                          # 前端类型 + 构建
cd frontend && npx tsc --noEmit                       # 仅类型检查（更快）
ruff check src tests                                  # lint
.venv/bin/python -m corpus2node.eval <session_id> --default-gold   # 离线 eval（需已有 session 产物）
```

## 当前最高优先级未完成功能

1. **记录真实 eval baseline 数字**（抽取 F1 / 问答 grounding / 出卷可溯源率）——需要用户凭据跑一份真实小语料，把数字写进本文件「已验证状态」。这是 §10 叙事的最后一块。
2. **Step 7 工程化收尾**：`Course→Corpus` 契约重命名（`core/types.py` + `frontend/src/types/index.ts` 一起改）、持久化向量库（Chroma，`VECTOR_STORE_PROVIDER` 可插拔）、Docker、README 补全。
3. （低优先）Plan-Execute-Report / FusionAgent 作为 chat 的可选 deep-research 子模式。

## 当前 blocker

- 无硬 blocker。唯一外部依赖：真实 LLM 端到端 + eval baseline 需要用户的 API 凭据与 token 预算（不能在 CI/无凭据环境完成）。

---

## 文件夹 → 功能映射（想增删改某功能，先来这里定位）

> 规则提醒（来自 CLAUDE.md §2）：确定性算法（中心性/聚类/合并/语义边/校验）是**普通函数**，绝不交给 LLM；同一套能力函数被「离线 workflow 节点」和「在线 agent 工具」共享 import。

### 后端 `src/corpus2node/`

| 路径 | 实现的功能 | 改这里当你想… |
|------|-----------|--------------|
| `config.py` | 基础设施配置（**无 LLM 槽**）：Kimi PDF/vision 配置、`embed_provider`、`graph_critic_enabled` 等开关 | 加基础设施开关 / 调 Kimi 解析参数 |
| `core/types.py` | **数据契约脊柱**：GraphArtifact / NoteDocument / ExamDocument / ChatDocument / EvidenceChunk / ConceptNode / GraphEdge / SourceKind / WorkflowRunArtifact | 改 wire 契约（**必须**和 `frontend/src/types/index.ts` 一起改） |
| `core/text.py` | 文本规范化 / 结构感知分块 / canonicalize | 调分块粒度 / 归一化规则 |
| `core/clock.py` · `core/logging_config.py` | `utcnow()`（naive UTC）· 日志配置 | 时间/日志 |
| `llm/credentials.py` `store.py` `factory.py` `structured.py` | **多凭据注册表 + 按 purpose 工厂**：登记凭据→绑定 graph/critic/chat/exam→`build_chat_model(Purpose)`；`structured_output_method`（openai=json_mode / anthropic=function_calling）；`make_structured` async caller | 加新 LLM purpose / 改结构化输出方式 / 改回退链 |
| `index/embeddings.py` · `index/search.py` | LangChain Embeddings（Hashing fallback / BGE-M3）· chunk/concept cosine 检索 + bounded subgraph | 换 embedding / 调检索 |
| `ingest/adapters.py` | **摄入适配器注册表** + kind 路由（md/txt/docx/pptx/csv/json/yaml + 各类型扩展名表） | **加新文件类型** |
| `ingest/chunk.py` `pdf_kimi.py` `image_kimi.py` `video_kimi.py` `audio_whisper.py` | 切块 · Kimi Files API file-extract（PDF 解析，**非 chat，几乎不计 token**）· Kimi vision（图片）· Kimi K2.6（视频 video_url）· faster-whisper（音频） | 调某模态的摄入方式 |
| `graph/extract.py` `prompts.py` `schemas.py` `clean.py` | 全量并发抽取（structured，no-sample）+ 抽取 prompt + 输出 schema + `is_junk_concept` 噪声过滤 | 调抽取质量 / prompt |
| `graph/build.py` | **建图皇冠**：语义合并(C) + Louvain 社区(A) + networkx 中心性 + 共现边(D) | 调建图算法 / 聚类 / 中心性 |
| `graph/critic.py` | **LLM-judge 质量门**：concept grounding / 关系方向 / 同实体重复 → 确定性 repair（drop/merge/flip/retype，≤1 轮，空图保护） | 调质量门规则 |
| `graph/workflow.py` | **LangGraph 离线 DAG**：ingest→extract→critic→build，每节点经 RunRecorder 记耗时/token/repair | 改离线流水线拓扑 |
| `notes/generate.py` `markdown.py` `prompts.py` `schemas.py` | **笔记**：map-reduce 分章（carry-forward 去重）+ 检索 chunk 落地引用 + **确定性 coverage critic** 补未覆盖核心概念；markdown.py 是 donor 来的确定性后处理 | 调笔记结构/覆盖 |
| `exam/generate.py` `validate.py` `prompts.py` `schemas.py` | **出卷**：generator + **verifier 独立求解回路**（solver 用 Purpose.critic 独立作答，不符/无据则打回补足到请求数）；validate 是题型/难度校验 + `answers_match` | 调出题/校验/难度 |
| `assistant/agent.py` `tools.py` | **招牌：在线 chat agent**（单 tool-calling agent + 强制引用 + 结构化 trace + SSE）；tools = retrieve_chunks / search_concepts / get_subgraph | 调问答行为 / 加 agent 工具 |
| `export/renderer.py` | 导出 md/tex/txt（纯 Python）+ pdf（惰性 wkhtmltopdf→xhtml2pdf，`[export]` extra）+ render_chat_markdown | 加导出格式 |
| `eval/metrics.py` `harness.py` `schemas.py` `__main__.py` `data/` | **离线评估**：纯指标（抽取 F1 / 关系合法+召回 / 笔记覆盖 / 出卷可溯源+客观题合法 / 问答 grounding）+ harness + CLI + gold fixture | 加评估指标 / 调 gold |
| `jobs.py` | **内存 detached async 任务表**：emit/finish/subscribe + 事件重放——notes/exam 流式生成存活于「请求断开/前端导航」之外 | 调后台任务/流式 |
| `prompt_store.py` | 用户自定义提示词（global + chat/notes/exam）作为「补充偏好」**追加**到内置 system prompt（不覆盖结构化/引用约束；抽取与质检不受影响） | 调自定义 prompt 接入面 |
| `storage/local.py` · `storage/run_artifact.py` | JSON artifact IO（事实来源）· RunRecorder（`get_usage_metadata_callback` 抓 token）+ WorkflowRunArtifact 持久化 | 调落盘 / 运行指标 |
| `api/app.py` + `api/routes/*` | FastAPI：sessions · settings(`/settings/llm` 注册表 CRUD) · prompts(`/settings/prompts`) · workflow(`/workflow/run` + run-metrics) · chat(`/chat/{message,stream}`) · notes(`/generate_notes[+/stream]`,`/notes/{id}[/stream]`) · exam(同形) · export(`/export/*`) · graph(`GET /graph/{id}`、`/subgraph`、`POST /search`、`GET /graph/concepts` 全局知识点搜索) | 加/改 HTTP 接口 |

### 前端 `frontend/src/`

| 路径 | 实现的功能 | 改这里当你想… |
|------|-----------|--------------|
| `api/client.ts` | **所有后端调用 + 共享 SSE pump**（契约耦合集中点） | 加/改一个后端调用 |
| `types/index.ts` | 前端契约（对应 `core/types.py`） | 改契约（和后端一起改） |
| `pages/HomePage.tsx` | 知识库列表 + **折叠（localStorage 记忆）** + **全局知识点搜索** + 来源标签(文档/视频/音频/图片) | 改首页/库管理 |
| `pages/NewSessionPage.tsx` | 上传建库（统一上传入口） | 改上传流程 |
| `pages/PipelinePage.tsx` | 流水线可视化 + **质检阶段** + per-node **run-metrics 面板**（耗时/token/repair） | 改流水线展示 |
| `pages/WorkspacePage.tsx` | 图谱 + 右栏**对话/笔记/试卷**标签页（选区可转对话 + ExportMenu） | 改主工作区 |
| `components/layout/SettingsPanel.tsx` | **统一设置**：模型（凭据列表 + 按 purpose 下拉绑定）/ 外观 / 提示词（真实编辑器） | 改设置面板 |
| `components/layout/CommandPalette.tsx` | ⌘K 命令面板 + **全局知识点搜索** | 改全局搜索/快捷入口 |
| `components/layout/{AppShell,TopBar}.tsx` | 外壳 / 顶栏 | 改全局布局 |
| `components/{chat,graph,notes,search,upload,primitives}/` | 各功能 UI 块（ReactFlow 图、引用卡、检索面板、上传等） | 改某块 UI |
| `hooks/ utils/ styles/` | 辅助 hooks / 工具 / 设计 token（theme.css） | 改主题/通用逻辑 |

### 其它

| 路径 | 功能 |
|------|------|
| `scripts/corpus.sh` | 启动器：`dev`（前台）/ `start|stop|status|logs|restart`（后台）；alias `corpus` 在 `~/.zshrc` |
| `tests/` | 后端测试（TestClient + 注入 seam 离线跑 LLM 路径 + `conftest` 用 tmp_path 隔离存储/重置 llm store 缓存） |
| `web/index.html` | 零构建最小验证 UI（挂 `/ui`，含凭据配置面板） |
| `docs/PROGRESS.md` · `docs/SESSION.md` | 本进度真相 · 会话交接摘要 |
| `CLAUDE.md` | 操作手册（定位/架构/原则/约定）；`AGENTS.md` 是其旧副本（已 stale，两者均 gitignore） |

---

## 会话记录（最新在上，每轮追加一条）

### 2026-06-25 — harness 落地 + 全局知识点搜索 + 知识库折叠
- **本轮目标**：(1) 「全局（对话/笔记/试卷 都生效）」标签改「全局」；(2) 两个搜索框支持搜全局知识点；(3) 知识库可折叠；(4) harness 工作：清理 CLAUDE.md、把进度迁到本文件、新增 SESSION.md。
- **已完成**：
  - 新增 `GET /graph/concepts`（跨所有已建图谱子串搜概念，按 importance 排序），接入 ⌘K 命令面板 + 首页工具栏；命中跳转到所属 session 图谱并聚焦该概念（`?concept=`）。
  - 首页知识库分组头改为点击折叠（chevron + localStorage 记忆）。
  - SettingsPanel 提示词首项标签 → 「全局」（细节移到 placeholder）。
  - harness：建 `docs/PROGRESS.md`（含文件夹→功能映射 + 会话记录）、`docs/SESSION.md`（交接摘要）；CLAUDE.md §1 巨型进度段落瘦身为指针、§9 完成态注解收成一行。
- **运行过的验证**：`pytest -q` → **105 passed**（1.2s）；ruff clean；前端最近一次 `npm run build` 在 `2a96b60` 通过（本轮只改 docs+CLAUDE，未动前端）。
- **已记录证据**：`tests/test_graph_routes.py::test_global_concept_search_route`（断言路由 200、命中含 session/course/concept、空 query→[]、不匹配→[]，且 `/graph/concepts` 在 `/graph/{id}` 之前解析）。
- **提交记录**：`36c995b`（feat: global concept search + collapsible knowledge bases）、`2a96b60`（chore: simplify prompt-settings 全局 label）；本轮 docs harness（PROGRESS/SESSION）+ CLAUDE 瘦身 = 本 docs 提交（`docs: add PROGRESS.md + SESSION.md harness`）。
- **已知风险或未解决问题**：全局概念搜索是**子串**匹配（即时、零 token），大规模库需要索引；语义模糊搜索未做。`corpus start` 后立刻 curl 抢跑 boot 偶返空（脚本时序，非 bug）。AGENTS.md 与 CLAUDE.md 已分叉（stale 副本）。
- **下一步最佳动作**：跑一份真实小语料记 eval baseline 数字（需用户凭据）→ 填入「当前已验证状态」。

### 2026-06-24 — 视频摄入 + 真实提示词设置 + 计费澄清
- **已完成**：`SourceKind.video` + `ingest/video_kimi.py`（Kimi K2.6 base64 `video_url`）；首页来源标签改 文档(含PDF)/视频/音频/图片；`prompt_store` + `/settings/prompts` 真实编辑器（用户文本作补充偏好追加，不覆盖结构化/引用约束）。
- **计费澄清**：`settings.kimi_*` 只用于 PDF file-extract（解析，非 completion，几乎不计 token）与图片/视频 vision；graph/chat/exam/critic 都绑 DeepSeek，token 花在 DeepSeek；注册表里 kimi 凭据未绑任何 purpose=未作对话模型。
- **提交记录**：`aa53067`、`3794055`。

### 2026-06-23 ~ 之前 — 见 commit 历史
- `901a762` eval harness（抽取 F1 / QA grounding / exam correctness）+ PipelinePage run-metrics 面板。
- `4eb65d1` graph critic（LLM-judge 质量门）+ WorkflowRunArtifact（每节点耗时/token/repair）。
- `231add0` 流式 notes/exam（detached job + SSE 重放）+ 统一设置面板 + 紧凑学习面板 + 图列向左收起。
- `4bb1cd6` corpus 启动器。
- `bc99427` notes/exam/export（map-reduce 笔记 + coverage critic / 出卷 verifier 回路 / md·tex·txt·pdf）+ 点亮前端右栏标签页。
- `29c443f` 及更早：LangChain/LangGraph MVP 重建（离线 workflow + 在线 chat agent + 多模态摄入 + 前端迁移对齐）。
