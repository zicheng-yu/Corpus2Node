# PROGRESS — Corpus2Node 进度真相

> **这是项目进度的唯一真相（single source of truth）。**
> 每轮新会话**先读本文件**（再读 `docs/SESSION.md` 拿最新交接），每轮结束**往「会话记录」追加一条**并更新顶部状态。
> 架构决策 / 原则 / 约定看 `CLAUDE.md`（操作手册，相对稳定）；本文件只管「现在到哪了、东西在哪、下一步做什么」。
> 写入纪律：只写**已验证**的事实（跑过测试 / 见过产物）。没验证的写进「已知风险」，不要写进「已验证状态」。

---

## 当前已验证状态

- **线上产品已收敛为个人账号版（2026-07-15）**：`ACCOUNT_PRODUCT_MODE=personal` 为默认和生产固定值；每个账号只绑定一个不可切换的私有资料库，底层 `Organization` 只承担资源/配额隔离，不在 UI 展示。设置弹窗只保留“账号 / 模型与 API / 外观 / 个人偏好”；团队、成员、平台管理和团队项目页不进入生产 bundle。线上 release `personal-byok-20260715-2010` 已部署。
- **HTTPS 测试服务器已上线并完成历史迁移（2026-07-15）**：阿里云 Ubuntu 22.04（4 vCPU / 16 GiB）运行 Docker Compose 的 PostgreSQL 17、FastAPI 后端和前端 nginx；宿主 nginx 通过有效 Let's Encrypt 证书发布 `https://corpus2node.digitmasterai.com`，容器入口仅绑定 `127.0.0.1:8080`。公网 `/api/health` 为 200，未登录业务/API 与模型设置均为 401，PostgreSQL/后端/前端重启恢复已验证。116 files / 122473324 bytes / SHA-256 `e73aa1e...9284c` 与本机完全一致；平台管理员已激活，3 projects / 62 resources 已登记，幂等复跑新增 0，62/62 artifact paths 均存在；迁移后 PostgreSQL dump 已生成。DeepSeek/Kimi `/models` 均验证成功。
- **后端测试 211 passed**（`.venv/bin/python -m pytest -q`，2026-07-15 实测；仅 1 条 Starlette/httpx 第三方弃用警告）。
- **账号与个人隔离已落地**：PostgreSQL/SQLite async ORM + Alembic；邮箱激活、Argon2 密码、opaque Cookie session、CSRF/Origin；每个账号自动采用已有 owner 资料库或创建新的 Free 个人资料库，请求头不能切到其他 membership，所有 artifact 仍经 `resources` 做 404 隔离。
- **团队底层延后而非删除**：项目自动修订、成员、分享与套餐后端保留在 `ACCOUNT_PRODUCT_MODE=teams`，供以后客户版复用；当前个人版不注册团队 UI 入口或团队项目页。固定 discovery/scientific 报告分享能力不受影响。
- **套餐与用量保留为个人账号边界**：Free/Team Beta 权益、只读降级和幂等用量继续作用于每个用户的隐藏个人资料库；生产 Compose 已加入 PostgreSQL、Alembic 和双层登录限流。
- **全离线 LLM 方案已落地并本机实测**：注册表 kind += `ollama`/`lmstudio`（免密钥、默认本地端点、`num_ctx`/`max_concurrency`）；本机 M3 用 `gemma4:e2b-it-qat` + `bge-m3`（嵌入）真 HTTP 跑通 workflow/chat/测试/models 全流程（`llama3.1:8b` 参照组同过）；PDF 无 Kimi 时 pypdf 本地解析、视频回退 whisper 音轨转写。
- **账号模式 BYOK 已完成**：Kimi（vision）、远程 embedding 与 chat 类用途都使用当前用户自己的注册表；账号模式路径为 `artifacts/users/<user_id>/llm_settings.json`，文件权限 600，API 只返回掩码。服务器环境/旧全局密钥不会注入新账号；本地 legacy 模式继续使用原 `artifacts/llm_settings.json`。托管模式只接受公网 HTTPS 模型 API，拒绝内网、loopback 和云端不可达的 Ollama/LM Studio。已登录用户可在保存前用 POST body 中的 endpoint/API Key 枚举模型，也可用已保存的 `credential_id` 重新读取并更新默认模型。
- **前端验证通过**（2026-07-15）：Vitest 8 文件 / 14 测试、TypeScript + Vite production build；覆盖首页携参跳转、统一历史筛选、所有账号可见的 BYOK 表单、保存后模型枚举与默认模型切换、力导向默认保留共现边、个人设置结构、TopBar 收缩和账号关闭兼容。
- **ruff clean**（`uv run ruff check src tests scripts`，2026-07-13 实测）。分支 `feat`。
- **离线闭环可跑**：上传 → workflow（ingest→extract→critic→build）→ GraphArtifact，离线 fixture e2e 通过；LLM 端到端（真实建图/问答/水平测试）**需用户用自己凭据在浏览器实测**（耗 token，CI 不覆盖）。
- **在线闭环可跑**：chat agent（强制引用 + trace + SSE）、notes（map-reduce + coverage critic）、水平测试（importance plan + generator + verifier 回路）、export（md/tex/txt/pdf）路由齐全且有测试覆盖。
- **多模态摄入**：文档 7 类 + PDF（Kimi file-extract ↔ 无 Kimi 时 pypdf 本地）+ 图片/视频（Kimi vision/K2.6；vision 绑本地 VLM 时图片走同路径、视频回退 whisper 音轨转写）+ 音频（faster-whisper），注册表式接入。
- **真实音频/视频摄入已复核（本轮）**：纯音频 `.mp3` 样本 `BV1m2P9zsEgW.mp3` 走 faster-whisper，session `72cc6407...` 为 `graph_ready`（6 chunks / 8 concepts / 1 relation）；标题为 “05 audio” 的 `.mp4` 实际按 `video` 路由，Kimi Files API + `ms://file_id` 真实调用成功，session `6c1a004f...` 为 `graph_ready`（5 chunks / 7 concepts / 9 relations）。
- **2026-07-13 全面审阅修复已落地并验证**：artifact 全 provenance 缓存与公开 DTO、source hash/embedding 失配检测、chat 引用编号与证据重合校验、scientific exact quote 与严格 bbox 匹配、科研仅摄入路径、artifact-backed 长任务事件、session 级并发锁、上传格式签名/解压上限、生产强制鉴权与 SSRF 防护、共现边限度、前端 graph 单次加载、SSE 长任务、访问 token 设置、OpenAPI/TS 契约快照、前端测试/依赖审计、Docker CI 与完整 README。
- **资料集 / 知识库重命名已落地**：后端支持单个资料集 `lecture_title` 改名与知识库 `course_title` 批量改名（含虚拟总图谱 session），首页支持内联入口；已通过全量 pytest、ruff、前端 build。
- **知识发现已落地并保存 artifact**：首页可多选资料集运行知识发现，也可随机发现；后端生成 `DiscoveryReport` 并保存到 `artifacts/discoveries/{discovery_id}.json`；支持 AI judge seam（critic 绑定可用时自动判断，失败/无凭据退回算法版）；已通过 `tests/test_discovery.py`、全量 pytest、ruff、前端 build。
- **知识发现增强已落地（本轮）**：(1) **桥接图可视化**——bridge graph 用 ReactFlow 三列（发现→知识点→资料集）画出来（懒加载独立 chunk，首页主包 376KB→229KB）；(2) **可溯源跳转**——发现卡片的概念 chip / 证据块、桥接图概念节点点击直达 `/session/{id}?concept=`；(3) **质量增强**——judge `relation_type` 约束到 8 类枚举（含中文别名回填）、证据每侧 top-2、加结构化信号（共享邻居/标签）、大候选池分批并发 judge、novelty 重算；(4) **历史面板**——首页列出历史 `DiscoveryReport`（`list_discovery_reports` 改按 `generated_at` 倒序），可点开重载。已通过 126 passed、ruff、前端 build。
- **知识发现中心整合已落地（2026-07-15）**：新增 `/discover` 双模式页面，统一资料选择、意图/研发目标、跨类型历史筛选和报告详情；跨资料发现仍走 `/discovery/*`，科研证据仍走 `/scientific/*`，旧 artifact/schema 不迁移。新增租户隔离的 `GET /discovery/history` 轻量索引；`/scientific` 兼容重定向到 `/discover?mode=scientific`；首页不再内嵌报告，TopBar 不再显示科研证据。随机发现只在跨资料模式可用，viewer 不能运行或修改提案，owner/admin/platform_admin 可删除历史。
- **历史知识发现可删除**：新增 `DELETE /discovery/{discovery_id}`、artifact 删除函数与首页历史条目删除确认；删除当前打开的报告会同步关闭面板，刷新后不再出现。
- **删除失败运行态问题已解决**：根因是前端 HMR 已加载新代码、后端仍是 7 月 6 日无 reload 的旧进程，DELETE 实际返回 405；已清理未受 pidfile 管理的旧进程并用 `corpus dev` 重启。真实 API 临时 artifact 删除 + 浏览器确认框/成功 toast 均通过，用户原 4 条报告未改动；前端遇到 405 现在明确提示重启后端。
- **“试卷”已迁移为“水平测试”**：前端不再选择题型；后端先按 `importance_score` 确定知识点测试计划，再让模型自动选题目形式并经独立求解器校验。主接口/产物为 `/generate_test`、`/test/*`、`test.json`、`test_id`；旧 `/exam`、`exam.json`、Python alias 保留读取兼容且从 OpenAPI 隐藏。
- **多客户策略再次收敛**：当前线上先做个人账号 + BYOK；团队协作和客户课题组作为后续独立产品模式，不再主导当前导航和账号模型。底层组织/项目实现保留，法规级物理隔离仍可独立部署同一套代码。
- **科研与 R&D 垂直方向已形成方案**：见 `docs/SCIENTIFIC_RD.md`；定位从通用概念图谱升级为“原始科技文献 → 科研实体/实验关系 → claim-evidence graph → 证据矩阵/矛盾/空白 → R&D 决策卡”，建议作为客户配置体系的首个 scientific profile。
- **科研证据图谱 MVP 技术主线已落地并真实验证**：新增独立 `scientific/` 垂直包、`/scientific` API 与“科研证据”页面；单篇抽取 Paper/Entity/Relation/Claim/Experiment，所有模型证据编号经后端映射并校验到真实 `session/source/chunk/locator`；跨论文生成证据矩阵、洞察和 R&D 决策卡，供应商 JSON 方言有边界归一化、限次重试、单篇内容指纹缓存及确定性证据综合兜底。用现有 VDN/QMIX + DeepSeek 真实跑通，报告 `f1c88905-7d9f-4434-9780-978e94bcd238`：2 papers / 19 entities / 19 relations / 10 claims / 3 experiments / 27 evidence / 2 insights / 1 decision；claim 引用有效率 **11/11**。内容策略为中文叙述，英文正式名称独立保留。
- **Scientific ingestion / N 元实验关系 / gold eval 主线已落地并真实批测**：JATS/TEI/GROBID 统一到 `ScientificDocument`，保存 section/sentence/page/bbox/table-cell/formula/citation；workflow 对 XML 优先结构解析、PDF 在 GROBID 可用时自动落 TEI，服务离线则不伪造 bbox且不阻断原摄入。Claim、Experiment、MetricResult、Condition、Evidence 与 Method/Dataset/Baseline 通过受角色约束的 N 元关系显式连接。桌面 MARL corpus 已有 131/131 PDF、30/30 GROBID TEI/JSON 和 30/30 DeepSeek silver。另完成 30 篇独立盲跑 AI proxy（`ai_verified`）：413 entities / 260 relations / 154 Claims / 61 numeric / 120 locators；内部一致性基线 Entity exact F1 0.3863、full-role Relation exact F1 0.0283、Claim fuzzy F1 0.4375、Claim/Numeric exact F1 0。Locator 0.9250 主要是页级一致率，不是句级准确率。人工 gold 继续只接纳 `verified`，详见 `docs/SCIENTIFIC_BENCHMARK.md`。
- **mixed 多模态抽取问题已修复（本轮）**：`06 mixed` 摄入正常（image 1 chunk + PDF 40 chunks），抽取阶段曾有 84 concepts / 60 relations，问题是 critic grounding 检索给大量真实概念提示“未检索到相关片段”，且近清空保护只拦截“全删”不拦截“84 删 83”。已改为字面证据优先 + embedding 补充，并加近清空保护；用旧 artifact 无外部调用复核可为 55/84 个旧 verdict 概念找到原文片段。

## 仓库根目录

`/Users/zicheng/Documents/Projects/Corpus2Node`
Donor / 只读参考仓库：`/Users/zicheng/Documents/Playground/Course2Note`

## 标准启动路径

```bash
corpus dev      # 前台同时起前后端（调试用，Ctrl-C 停）；脚本 scripts/corpus.sh，alias 在 ~/.zshrc
corpus start     # 后台起，日志在 .run/logs/{backend,frontend}.log
corpus status    # 看进程/端口
corpus stop      # 停 pidfile 记录的后台进程；强制清端口用 corpus force-stop
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

1. **完成 30 篇科研 gold 的人工双审**：AI blind proxy 内部基线已完成，但不能替代专家标注；需领域标注者把 silver 校正并裁决为 `verified`，才能记录 human-gold accuracy。
2. **完成个人账号真实浏览器验收**：管理员确认历史资料和原 3 凭据 / 6 bindings 可用；演示账号确认空个人资料库、独立配置 API、上传和发现流程，且不能看到管理员的 15 个历史 session。
3. **记录真实 eval baseline 数字**（抽取 F1 / 问答 grounding / 水平测试可溯源率）。
4. **后续 SaaS 专项**：自助注册/邮件服务、支付、对象存储和外部任务队列；当前由 `corpus2node-admin invite-user` 生成个人激活链接，单 worker 符合首版范围。团队客户版另行规划。
5. （低优先）Plan-Execute-Report / FusionAgent 作为 chat 的可选 deep-research 子模式。

## 当前 blocker

- 30 篇 AI blind proxy 与内部一致性分数已经完成，但它复用同一 prompt/schema/page-selection 管线，只能标为 `ai_verified`。**AI proxy 不能冒充 human gold**；专家准确率仍依赖领域标注者双审、争议裁决并改为 `review_status=verified`。

---

## 文件夹 → 功能映射（想增删改某功能，先来这里定位）

> 规则提醒（来自 CLAUDE.md §2）：确定性算法（中心性/聚类/合并/语义边/校验）是**普通函数**，绝不交给 LLM；同一套能力函数被「离线 workflow 节点」和「在线 agent 工具」共享 import。

### 后端 `src/corpus2node/`

| 路径 | 实现的功能 | 改这里当你想… |
|------|-----------|--------------|
| `config.py` | 基础设施配置（**无任何 LLM 凭据**，连 Kimi/embedding 都在注册表）：API 安全开关、上传大小、`vision_timeout_seconds`、`embed_provider`、`embedding_dimensions`、`graph_critic_enabled`、whisper 等开关 | 加基础设施开关 / 调超时 |
| `accounts/` · `admin.py` | SQLAlchemy async 元数据层；个人账号隐藏资料库、session/CSRF、Free/Team 权益、资源登记、用量、artifact 导入；`invite-user` 与个人工作区迁移 CLI；teams 模式底层保留 | 改身份、个人隔离、套餐、迁移或后续团队模式 |
| `projects/revisions.py` | 项目级 debounce + 串行/dirty-rerun；版本指纹、公共图谱重建、科研 map-reduce、原子 latest 切换和增删摘要 | 改团队聚合与修订策略 |
| `core/types.py` | **数据契约脊柱**：GraphArtifact / NoteDocument / TestDocument / ChatDocument / DiscoveryReport / DiscoveryHistoryItem / EvidenceChunk / ConceptNode / GraphEdge / SourceKind / WorkflowRunArtifact；旧 Exam 类型为兼容 alias | 改 wire 契约（**必须**和 `frontend/src/types/index.ts` 一起改） |
| `core/text.py` | 文本规范化 / 结构感知分块 / canonicalize | 调分块粒度 / 归一化规则 |
| `core/clock.py` · `core/logging_config.py` | `utcnow()`（naive UTC）· 日志配置 | 时间/日志 |
| `llm/credentials.py` `store.py` `factory.py` `structured.py` | **每用户多凭据注册表 + 按 purpose 工厂**：账号模式由 request/background context 绑定 `user_id` 并保存 600 文件；本地/legacy 保持单注册表。**kind** = `openai`/`anthropic`/`ollama`/`lmstudio`，**purpose** = `graph/critic/chat/exam/vision/embedding`；Ollama 原生客户端、结构化输出方言、并发与上下文策略保持不变 | 加新 LLM kind/purpose / 改 BYOK 隔离、结构化输出、回退链或并发 |
| `index/embeddings.py` · `index/search.py` | LangChain Embeddings（hashing / 本地 BGE-M3 / **注册表 `embedding` 用途：ollama kind→OllamaEmbeddings 原生批量，其余→OpenAIEmbeddings 且非官方端点自动 `check_embedding_ctx_length=False`**——否则发 tiktoken token 数组，本地/DeepSeek 端点 400）· chunk/concept cosine 检索 + bounded subgraph | 换 embedding / 调检索 |
| `ingest/kimi_client.py` | **vision 客户端**：从注册表 `vision` 用途解析 (base_url/api_key/model) 建 openai SDK client（本地 VLM 同样走这条）；`vision_is_moonshot()` 门控 Moonshot 专属能力（Files API file-extract、`ms://` 视频上传、K2.6 关思考 extra_body） | 改 vision 凭据解析 / 多模态超时 / moonshot 判定 |
| `ingest/adapters.py` | **摄入适配器注册表** + kind 路由（md/txt/docx/pptx/csv/json/yaml/JATS/TEI + 各类型扩展名表）；科研 XML 优先结构解析；**PDF 双路**：vision 绑 Kimi→file-extract（含 OCR），否则→`pdf_local.py`（pypdf 全离线，扫描件报错指向 Kimi） | **加新文件类型** / 改 PDF 路由 |
| `ingest/chunk.py` `pdf_kimi.py` **`pdf_local.py`** `image_kimi.py` `video_kimi.py` `audio_whisper.py` | 切块 · Kimi Files API file-extract（PDF 解析，**非 chat，几乎不计 token**）· **pypdf 本地 PDF 文本层**（离线路径，逐页块保留页码 locator）· vision 图片（Kimi 或本地 VLM；K2.6 专属参数按 moonshot 门控）· 视频：Kimi 时 Files API `purpose=video` 上传 + `ms://file_id`；**非 moonshot 时回退 faster-whisper 转写视频音轨（PyAV 解容器，纯视觉无声视频除外）** · **音频 = faster-whisper 本地转写**（Kimi 平台 API 不接受音频输入；faster-whisper 为 **core 依赖**） | 调某模态的摄入方式 / 换音频模型 |
| `graph/extract.py` `prompts.py` `schemas.py` `clean.py` | 全量并发抽取（structured，no-sample）+ 抽取 prompt + 输出 schema + `is_junk_concept` 噪声过滤；merge 末尾 **`_reconcile_relation_endpoints`**：关系端点经概念 name/canonical/别名映射归一（小模型常给端点写表面名导致悬空关系被 critic 全丢，云端模型同样受益） | 调抽取质量 / prompt / 端点归一 |
| `graph/build.py` | **建图皇冠**：语义合并(C) + Louvain 社区(A) + networkx 中心性 + 每节点有上限的强共现边(D) | 调建图算法 / 聚类 / 中心性 |
| `graph/critic.py` | **LLM-judge 质量门**：concept grounding / 关系方向 / 同实体重复 → 确定性 repair（drop/merge/flip/retype，≤1 轮，空图保护） | 调质量门规则 |
| `graph/workflow.py` | **LangGraph 离线 DAG**：ingest→extract→critic→build；source/schema/prompt/model/embedding/config 完整 provenance 缓存；支持科研路径 ingest-only；每节点经 RunRecorder 记耗时/token/repair | 改离线流水线拓扑 / 缓存依赖 |
| `notes/generate.py` `markdown.py` `prompts.py` `schemas.py` | **笔记**：map-reduce 分章（carry-forward 去重）+ 检索 chunk 落地引用 + **确定性 coverage critic** 补未覆盖核心概念；markdown.py 是 donor 来的确定性后处理 | 调笔记结构/覆盖 |
| `exam/generate.py` `validate.py` `prompts.py` `schemas.py` | **水平测试**：确定性按 `importance_score` 规划知识点 → generator 自动选题目形式 → **verifier 独立求解回路**；目录名与 `Purpose.exam` 暂留作内部兼容键 | 调测试覆盖/校验/难度 |
| `assistant/agent.py` `tools.py` | **招牌：在线 chat agent**（单 tool-calling agent + 最近历史 + 预检索 + 引用编号/证据重合校验 + 只返回实际使用引用 + 校验后 SSE + 结构化 trace）；tools = retrieve_chunks / search_concepts / get_subgraph | 调问答行为 / 加 agent 工具 |
| `discovery/engine.py` | **知识发现 v2（创新提案）**：多资料集/随机模式；宽候选生成（相似度+词面+结构信号+图谱重要性）+ AI judge seam（Purpose.critic，大池分批并发，`relation_type` 8 类枚举+中文别名回填）+ 算法 fallback；证据每侧 top-2；LLM 标题 seam（确定性 `derive_title` 回退）。**提案层（老板场景）**：findings → `make_proposer_or_none`（Purpose.chat→critic，temp 0.7，json_mode 需 prompt 带 `_PROPOSAL_FORMAT_HINT`）产出 `InnovationProposal`（title/pitch/组合/第一步/风险/status/deep_dive）；`_proposals_from_draft` 概念 grounding（名称多键映射：raw+去括号，同名跨集解析**优先未覆盖资料集**）+ 跨集 ≥2 校验；`_fallback_proposals` 按 relation_type 模板确定性成案；`_avoid_titles` 把历史已采纳/搁置标题喂给 proposer 避重；`deepen_proposal` + `make_deepener_or_none` 五字段深挖（目标/做法/数据/首实验/指标）确定性渲染 markdown；`intent` 全程贯穿 prompt。**桥接图 v2**：有提案时输出 资料集→概念→提案 三层（node_type=proposal 带 status/pitch），无提案回退旧 finding 布局（老报告兼容） | 调发现/提案逻辑 / 评分权重 / 提案数(`_PROPOSAL_TARGET`) / 深挖字段 / 图布局 |
| `scientific/schemas.py` `parsers.py` `evaluation.py` `prompts.py` `engine.py` | **科研证据图谱**：JATS/TEI/GROBID 结构与坐标；类型化实体/Claim/Experiment/Metric/Condition/Evidence 和受约束 N 元关系；Claim/数值 exact evidence quote 校验；对称一对一 bbox 指标；跨论文矩阵/R&D 决策；`ai_verified` proxy 与人工 `verified` 分轨评测 | 调科研本体 / 结构解析 / N 元关系 / gold 指标 / 跨论文决策 |
| `export/renderer.py` | 导出 md/tex/txt（纯 Python）+ pdf（惰性 wkhtmltopdf→xhtml2pdf，`[export]` extra）+ render_chat_markdown | 加导出格式 |
| `eval/metrics.py` `harness.py` `schemas.py` `__main__.py` `data/` | **离线评估**：纯指标（抽取 F1 / 关系合法+召回 / 笔记覆盖 / 水平测试可溯源+客观题合法 / 问答 grounding）+ harness + CLI + gold fixture | 加评估指标 / 调 gold |
| `jobs.py` | **artifact-backed detached async 任务表**：emit/finish/subscribe + 有界事件重放 + 同参数复用/异参数冲突保护；完成状态可跨重启读取，执行仍为单进程——notes/test/scientific/discovery 流式生成 | 调后台任务/流式 |
| `prompt_store.py` | 用户自定义提示词（global + chat/notes/exam）作为「补充偏好」**追加**到内置 system prompt（不覆盖结构化/引用约束；抽取与质检不受影响） | 调自定义 prompt 接入面 |
| `storage/local.py` · `storage/run_artifact.py` | JSON artifact IO（事实来源，原子写；含 `discoveries/` 与 `scientific/` 报告）· RunRecorder（`get_usage_metadata_callback` 抓 token）+ WorkflowRunArtifact 持久化 | 调落盘 / 运行指标 |
| `api/app.py` + `api/routes/*` | FastAPI：`disabled/legacy_token/accounts` 三模式；Cookie/CSRF/Origin、租户资源依赖与跨租户 404；auth/organizations/admin/projects/shares + 原 sessions/workflow/chat/notes/test/scientific/discovery/export/SSE；生产关闭 docs/traceback | 加/改 HTTP 接口或授权边界 |

### 前端 `frontend/src/`

| 路径 | 实现的功能 | 改这里当你想… |
|------|-----------|--------------|
| `api/client.ts` · `auth/AuthContext.tsx` | 所有后端调用 + SSE；Cookie credentials、CSRF、个人资料库内部 header 与旧 Bearer 兼容；前端不提供组织切换 | 加/改调用、认证或个人账号上下文 |
| `types/index.ts` | 前端契约（对应 `core/types.py`，含 DiscoveryReport） | 改契约（和后端一起改） |
| `pages/HomePage.tsx` | 纯知识库/资料管理：列表、折叠/拖拽、改名、筛选与全局知识点搜索；资料多选只负责携带重复 `session` 参数进入 `/discover` | 改首页/库管理/发现入口 |
| `pages/{Login,Activate,Share}Page.tsx` | 个人账号激活/登录与安全快照分享；Projects/Project/TeamSettings/PlatformAdmin 源码暂留给后续 teams 模式，但当前 App 不引用、不打包 | 改当前账号/分享体验或后续协作产品 |
| `pages/DiscoverPage.tsx` · `components/scientific/ScientificReportView.tsx` | **知识发现中心**：跨资料/科研证据双模式，共用资料选择和轻量历史时间线；按模式调用独立 SSE/schema，按角色限制运行、删除与提案操作；科研报告视图可复用 | 改发现中心信息架构 / 科研证据呈现 |
| `pages/ScientificPage.tsx` | 旧科研页面实现保留作组件兼容；公开路由 `/scientific` 已重定向到 `/discover?mode=scientific` | 清理旧实现或排查历史兼容 |
| `components/discovery/BridgeGraphView.tsx` | **发现呈现图（双布局自适应）**：有 proposal 节点 → **部门(资料集)→桥接概念→创新提案** 三列（提案宽卡、采纳高亮 ring/搁置降透明、点击提案定位卡片）；旧报告（finding 节点）保留 发现→知识点→资料集 布局；概念节点点击溯源；懒加载独立 chunk | 改呈现图样式/布局/交互 |
| `pages/NewSessionPage.tsx` | 上传建库（统一上传入口；全部失败不进入流水线） | 改上传流程 |
| `pages/PipelinePage.tsx` | 流水线可视化（4 阶段一行：解析/切分/抽取/构建，**质检 critic 折叠进「构建图谱」**）+ per-node **run-metrics 面板**（耗时/token/repair，仍单列 `critic` 节点） | 改流水线展示 |
| `pages/WorkspacePage.tsx` | 图谱 + 右栏**对话/笔记/测试**标签页（选区可转对话 + ExportMenu）；测试只选题数，覆盖按知识点重要度自动规划 | 改主工作区 |
| `components/layout/SettingsPanel.tsx` | **统一设置**：模型（凭据=端点+密钥+模型 一体；用途 graph/chat/critic/exam/**vision/embedding** 各一个单选下拉「凭据·模型」直接绑）/ 外观 / 提示词（真实编辑器） | 改设置面板 |
| `components/graph/ConceptGraph.tsx` `layoutUtils.ts` | ReactFlow 概念图与力导向/径向/聚类布局；共现边默认参与显示和布局计算，避免节点被误判为孤立节点 | 改图谱节点、边样式或布局参数 |
| `components/layout/CommandPalette.tsx` | ⌘K 命令面板 + **全局知识点搜索** + 按 session 状态跳转 | 改全局搜索/快捷入口 |
| `components/layout/{AppShell,TopBar}.tsx` | 外壳 / 顶栏 | 改全局布局 |
| `components/{chat,graph,notes,search,upload,primitives}/` | 各功能 UI 块（ReactFlow 图、引用卡、检索面板、上传等） | 改某块 UI |
| `hooks/ utils/ styles/` | 辅助 hooks / 工具 / 设计 token（theme.css） | 改主题/通用逻辑 |

### 其它

| 路径 | 功能 |
|------|------|
| `scripts/corpus.sh` | 启动器：`dev`（前台）/ `start|stop|force-stop|status|logs|restart`（后台）；alias `corpus` 在 `~/.zshrc` |
| `scripts/grobid.sh` · `collect_marl_top3.py` · `preannotate_scientific_gold.py` · `review_scientific_gold.py` · `parse_scientific_corpus.py` · `evaluate_scientific_gold.py` · `run_scientific_benchmark.py` | 本机 GROBID 生命周期 · MARL 高召回候选/PDF · 真实 API silver/AI blind proxy · GROBID TEI/locator 回填 · 人工 verified/AI proxy 分轨评测 |
| `.github/workflows/ci.yml` | 最小 CI：后端 uv sync + ruff + pytest；前端 npm ci + build |
| `tests/` | 后端测试（TestClient + 注入 seam 离线跑 LLM 路径 + `conftest` 用 tmp_path 隔离存储/重置 llm store 缓存） |
| `web/index.html` | 零构建最小验证 UI（挂 `/ui`，含凭据配置面板） |
| `docs/PROGRESS.md` · `docs/SESSION.md` | 本进度真相 · 会话交接摘要 |
| `docs/demo/` | **产品演示套件**：`DEMO.md`（六幕图文 + 3–5min 现场台本 + runbook）· `assets/`（10 张实拍截图）· `Corpus2Node-演示.pptx`（11 页，deck.js 可重建）；演示数据 = 主秀库「Python 程序设计」(b4f59dff) + 发现「Reinforcement Learning · 4 提案」 |
| `docs/DEPLOYMENT_MODELS.md` | 生产开源模型三档推荐（vLLM 参数 + 注册表绑定表 + 显存速查） |
| `deploy/docker-compose.cn.yml` | 国内网络部署覆盖：DaoCloud 基础镜像、阿里 Debian 镜像、清华 PyPI artifact 镜像；默认关闭不可拉取的 GROBID profile |
| `CLAUDE.md` | 操作手册（定位/架构/原则/约定）；`AGENTS.md` 是其旧副本（已 stale，两者均 gitignore） |
| `README.md` | 本地启动、主要能力、验证命令、OpenAPI 契约生成与安全 Docker 部署说明 |

---

## 会话记录（最新在上，每轮追加一条）

### 2026-07-27 — 本地改动按功能整理提交
- **提交边界**：将 7 月 15 日遗留工作树拆为部署可移植性、个人资料库/每用户 BYOK 与统一发现中心、力导向图共现边回归、文档交接四组 Conventional Commits；未执行 push。
- **验证**：`.venv/bin/python -m pytest -q` → **211 passed**（1 条第三方弃用警告）；`.venv/bin/ruff check src tests` clean；前端 Vitest **8 files / 14 tests**；`npm run build` 通过。
- **保留项**：`frontend/src/pages/SettingsPage.tsx` 与 `SettingsPage.test.tsx` 是设置恢复为 modal 前留下、且未被应用入口引用的未跟踪中间文件；按文件删除确认规则未擅自清理，也未纳入提交。

### 2026-07-15 (6) — 个人账号 + 每用户 BYOK 上线
- **产品边界**：新增 `ACCOUNT_PRODUCT_MODE=personal|teams`，默认及生产固定 personal。每个用户通过 `users.personal_organization_id` 固定到一个隐藏个人资料库；已有 owner 工作区原地采用，只有 shared member membership 的账号新建空 Free 资料库。个人模式忽略组织切换 header，`/auth/me` 和 `/organizations` 只返回个人资料库，成员/邀请/组织修改端点关闭。
- **BYOK**：`llm.store` 用 ContextVar 把 HTTP、SSE、后台任务和用量记录绑定到当前 `user_id`，注册表落 `artifacts/users/<user_id>/llm_settings.json` 并强制 600；普通账号可完整管理 provider / `base_url` / `api_key` / model / purpose，响应仍只回掩码。托管环境拒绝本地 kind、HTTP、loopback 和私网 IP；local/legacy 不受影响。
- **界面与运维**：设置 modal 只保留账号、模型与 API、外观、个人偏好；账号页移除角色、工作区切换和平台标记；`/team`、`/admin`、`/projects/:id` 回首页，团队/平台页面不进 bundle。新增 `invite-user` 与幂等 `migrate-personal-accounts` CLI。
- **验证/上线**：后端 **210 passed**、ruff clean、SQLite/PostgreSQL Alembic `20260715_0002`、前端 7 files / **12 tests**、production build、OpenAPI/TS 生成和 `git diff --check` 通过。线上 release `personal-byok-20260715-2010` 健康；2 users 均已迁移，管理员采用 Imported Workspace，demo 用户得到 `member 的资料库`；管理员 3 credentials / 6 bindings 已无明文输出地复制到个人 600 文件。原删除目标现已 archived，并形成 ready 项目修订，因此资源数为 63。

### 2026-07-15 (5) — member 资料归档修复与设置弹窗恢复
- **线上根因**：目标 session `8ac66ee6-34a5-4c0e-917f-009b028fe8f0` 的 DELETE 实际返回 403；演示账号是 `member`，旧接口却要求 `admin`。现允许 `member` 归档团队资料，`viewer` 仍只读；删除只把 session/source 资源标为 archived 并触发项目修订，不物理删除 JSON artifact。
- **设置体验**：TopBar 设置入口从全屏 `/settings` 页面恢复为 modal；账号、团队、外观、个人提示词继续在弹窗内，platform_admin 额外看到原有“模型与 API”和平台管理。模型表单保留 provider、`base_url`、`api_key`、模型读取及 purpose 绑定；旧 `/settings`、`/team`、`/admin` 深链接继续打开对应弹窗区段。
- **验证/部署**：后端 **208 passed**、ruff clean、`git diff --check`；前端 7 files / **12 tests**、production build。线上 release `settings-modal-delete-20260715-1945` 健康，首页与设置链接 200，数据库仍为 2 users / 62 resources，目标 session 仍为 active，未替用户自动重试删除。

### 2026-07-15 (4) — 知识发现中心整合与线上发布
- **统一入口**：新增 `/discover`，常驻“跨资料发现 / 科研证据分析”模式切换；首页任何有源文件的非虚拟 session 均可勾选并以重复 `session` 参数进入。跨资料要求图谱就绪且后端继续校验 embedding 指纹，空选走随机；科研只要求源文件且空选禁用。
- **统一历史**：新增 `DiscoveryHistoryItem` 与 `GET /discovery/history`，在账号模式只读取当前组织已登记且 active 的两类报告资源，按生成时间倒序返回轻量计数；详情、删除、SSE 和 JSON artifact 仍分别走原 discovery/scientific 契约。
- **界面/权限/兼容**：发现中心采用左侧配置与历史、右侧报告；历史支持全部/跨资料/科研证据筛选和按需加载，通用提案采纳/搁置/深挖、桥接图和科研 locator 保留。TopBar 删除科研证据，首页移除内嵌报告；`/scientific` 兼容重定向。member 可运行但不可删历史，viewer 不能运行或修改提案，账号关闭模式保持可写。
- **验证/部署**：后端 **207 passed**、ruff clean；前端 6 files / **11 tests**、production build、OpenAPI/TS 契约重生成、`git diff --check`。线上 release `discovery-center-20260715-1920` 健康，`/discover` 200、未登录 `/api/discovery/history` 401；PostgreSQL 仍为 2 users / 62 resources / 2 organizations。Chrome 页面控制超时，未消耗待激活的 demo member 邀请；普通角色行为由自动化测试覆盖。

### 2026-07-15 (3) — 项目首页体验回退与 TopBar 再收缩
- **首页回退**：账号模式 `/` 不再渲染 `ProjectsPage` 的团队项目卡片，恢复原 `HomePage`；重新提供知识库/资料集分组、全局搜索、状态筛选、拖拽排序、知识发现和历史报告。团队 Project、自动修订、权限与 `/projects/{id}` 深链接未删除，后续以原首页交互为基线重新设计协作入口。
- **TopBar 收缩**：删除工作区下拉、用户名与“成员”角色，只保留产品导航、搜索和设置齿轮；账号/角色仍在“设置 → 账号”，工作区切换也移入“我的工作区”。
- **验证与部署**：Vitest 4 files / **7 tests**；TypeScript + Vite production build；`git diff --check`；主 bundle 约 271.2KB -> 267.7KB。线上 release `ui-personal-projects-20260715` 健康，`/`、`/settings?section=account`、`/api/health` 均 200，线上 bundle 含“我的知识库”且不含“团队项目”。

### 2026-07-15 (2) — 设置中心重构与普通 member 演示视角
- **信息架构**：顶部导航删除“团队”“平台管理”，只保留日常工作；齿轮和用户信息均进入独立 `/settings`。旧 `/team`、`/admin` 链接保留重定向兼容。
- **统一设置**：新增账号、团队与成员、外观、个人偏好；仅 platform_admin 额外看到模型与密钥、平台管理。账号页支持查看工作区/角色、修改密码与退出；平台维护权限只在账号设置内轻提示。
- **普通用户体验**：`platform` 内部组织不再出现在工作区选择器；有客户工作区时默认选客户工作区。Team/Platform 页面改 lazy chunk，普通成员不下载管理员页面代码；主 bundle 约 280.9KB -> 271.2KB。
- **真实演示账号**：为 `Imported Workspace` 创建 `yuzichengyzc+demo@gmail.com` 的 member 邀请，待用户通过一次性链接设置密码。该账号能查看/上传/分析团队资料，但无平台运营、模型密钥、套餐和成员管理权限。
- **验证与部署**：Vitest 4 files / **7 tests**；TypeScript + Vite production build；React 最佳实践复核通过（named exports、语义 nav/link、权限派生、lazy loading）；线上新 release `dac3dea-settings-ui-20260715` 健康，PostgreSQL 仍为 1 active user / 62 resources，公网 `/settings` 与 `/api/health` 均 200。

### 2026-07-15 — 阿里云 HTTPS 部署、历史 artifact 预迁移与国内镜像适配
- **服务器**：Ubuntu 22.04 / 4 vCPU / 16 GiB 安装 Docker 29.1.3 + Compose 2.40.3；版本化目录 `/opt/corpus2node/releases/dac3dea`、共享 artifact/环境/备份目录与 `current` symlink 已建立。PostgreSQL、backend、frontend nginx 容器均运行，8080 仅 loopback；外层 nginx 的域名、HTTP→HTTPS 与 Let's Encrypt TLS 均验证。
- **国内构建**：Dockerfile 的 registry/Debian/PyPI artifact host 参数化，新增 `docker-compose.cn.yml`；解决 frozen `uv.lock` 仍直连 files.pythonhosted.org 的慢下载。生产启动改为直接调用 `.venv/bin/alembic`/`uvicorn`，避免容器重启联网检查依赖。
- **迁移兼容**：`load_session` 对从其他机器复制来的绝对 source 路径按当前 `session/uploads` 读取时重定位，不改写 JSON；inventory 排除 `.DS_Store`/AppleDouble。服务器与本机 dry-run 完全一致：116 files / 122473324 bytes / SHA-256 `e73aa1e...9284c`，15 sessions / 3 projects / 17 sources / 15 graphs / 4 scientific / 2 discovery / 9 private artifacts。
- **安全/模型验证**：生产 `AUTH_MODE=accounts`；未登录 `/auth/me`、`/sessions`、`/settings/llm` 均 401；`llm_settings.json` 权限 600，DeepSeek/Kimi 密钥只做 `/models` 可用性探测且均成功。公网 8080 不可达，容器和 PostgreSQL 重启后健康与管理员邀请均保留。
- **测试**：账号、会话、迁移相关 **24 passed**；新增迁移兼容测试 2 passed；`git diff --check`、Compose config 与远端 Alembic `20260714_0001` 通过。
- **正式迁移**：平台管理员 `yuzichengyzc@gmail.com` 已激活；创建 `Imported Workspace`（Team Beta）和 3 个项目，登记 62 个资源，幂等复跑新增 0；数据库中旧 Mac path 为 0，62/62 artifact paths 存在。迁移后 dump 位于服务器 `shared/backups/post-migration-20260715-175257/`（SHA-256 `2c60e921...e0ced9b`）。GROBID 在该国内镜像返回 403，当前云 API 演示栈默认不启用其 profile。

### 2026-07-14 — 账号、托管多租户、团队项目修订、套餐与分享
- **身份/租户**：新增 async SQLAlchemy、PostgreSQL/SQLite、Alembic 初始迁移；邮箱邀请激活、Argon2、30 天 opaque Cookie session、CSRF/Origin、角色矩阵、平台后台和 bootstrap CLI。生产 `AUTH_MODE=accounts`，旧 Bearer 仅兼容模式保留。
- **隔离/套餐**：所有业务路由接入组织资源登记与跨租户 404；Chat/笔记/测试/提示偏好按用户私有；Free/Team Beta、覆盖额度、只读降级、幂等用量与模型签名已接入。公开 session/graph DTO 不含内部路径或 embedding。
- **协作/修订**：稳定 Project 取代 `course_title` 临时分组；连续上传合并为项目修订，复用单篇缓存重建公共图谱，scientific 项目最多 100 篇 map-reduce；失败保留上一稳定版本，停用来源触发排除修订。
- **分享/界面/迁移**：固定修订/报告的 256-bit hash-token 独立 JSON 白名单快照；新增账号、组织、团队、平台、项目与分享页面，平台页含试用/额度覆盖和全局用量；artifact 导入支持 dry-run、数量/hash 核对且不移动原文件；Compose 加 PostgreSQL、Alembic 和登录限流。
- **验证**：ruff clean；pytest **204 passed**；Vitest 4 tests；OpenAPI/TS 快照重新生成；TypeScript + Vite production build、Alembic 初始迁移和 Compose 配置解析通过。未调用真实 LLM、未运行远程服务、未 push。

### 2026-07-13 (2) — 全面项目审阅修复：正确性、安全、持久化、前端与工程化
- **artifact / 缓存**：source SHA-256、graph schema/provenance（source/model/prompt/config/embedding）与自动失效；公开 Graph DTO 移除 embedding 但保留 evidence；旧无指纹图谱在向量检索前明确要求重建；跨图发现拒绝混用 embedding 空间。
- **grounding / scientific**：chat 校验引用编号、只回实际使用引用并做保守证据词面重合检查，SSE 先校验后输出；科学 Claim/Metric 必须保存原文 exact quote，bbox 改严格对称一对一；修复 vendor normalizer 丢弃已实例化 Metric/Insight/DecisionCard；科研路径只摄入不建通用图。
- **任务 / 并发 / 性能**：notes/test/scientific/discovery 长任务事件落盘并可重启后重放；session/report keyed lock 防并发覆盖且无锁表泄漏；共现边每节点封顶、前端默认隐藏；Workspace 图谱单次加载；首页发现报告拆为独立组件。
- **安全 / 部署**：生产强制 accounts + PostgreSQL、Cookie/CSRF/Origin 与登录限流，关闭 docs/traceback/type 泄漏；模型探测限制与 URL 校验；上传分格式上限、magic/Office 结构/解压上限；Docker 仅 loopback 暴露 nginx，GROBID/backend/PostgreSQL 内网；Vercel 仅临时预览。
- **契约 / 工程化**：补 README、`.env.example`、依赖声明；OpenAPI JSON + TS 自动类型快照；Vitest/Testing Library；CI 覆盖 ruff、pytest、契约漂移、前端测试/build/audit、Docker build；npm audit 修至 0。忽略无 `session.json` 的孤儿 UUID 目录，不删除用户 artifact。
- **验证**：`pytest -q` 194 passed；ruff clean；Vitest 2 files / 4 tests；Vite production build；npm audit 0；OpenAPI/TS snapshot 无漂移；Compose config 解析通过；现有 15 sessions、4 scientific reports 新 schema 只读加载通过。未调用真实 LLM、未修改/提交用户的 `docs/demo/*.pptx`。

### 2026-07-13 — 30 篇 AI blind proxy 标注 + 正式内部一致性测试
- **独立标注**：冻结原 30 篇 silver prediction（逐文件 SHA-256），从 PDF 选页独立调用模型盲标；统一裁决 evidence ID 与 N 元必需角色，最终 30/30 `ai_verified` reference：413 entities / 260 relations / 154 Claims / 61 numeric / 120 locators。
- **分轨准入**：审计发现 AI reference 不能占用人工双审 `verified`，新增 `ai_verified`；默认 evaluator 仍只准入人工 `verified`，内部 benchmark 显式只准入 `ai_verified`。
- **真实基线**：Entity exact F1 0.3863；完整角色 Relation exact F1 0.0283；启发式 Claim fuzzy F1 0.4375；Claim exact/Numeric 四字段 exact F1 均为 0。页面/table locator key agreement 0.9250，GROBID-derived bbox-set agreement 0.9237。
- **审计结论**：独立实验审计为 WARN——无 prediction 直接泄漏，当前 artifact 可重算；但 reference 复用 prompt/schema/page-selection，属于相关 AI proxy，不是 human gold。120 个 locator 中 115 个仅页级，locator 分数不得解释为句级 grounding accuracy。
- **审计链**：prediction/reference manifest 均校验目录文件集合、bytes、SHA-256；reference 额外固化并校验 prompt 原文与 30 个源 PDF hash；结果记录 manifest/prompt digest、指标口径、locator 粒度和论文级 bootstrap 限制。完整说明见 `docs/SCIENTIFIC_BENCHMARK.md`，本机结果与审计在桌面 corpus 的 `results/`。
- **验证**：pytest **176 passed**；ruff clean；真实 30 篇 benchmark 重跑通过；GROBID 健康。

### 2026-07-12 — JATS/TEI/GROBID + N 元实验关系 + 30 篇 MARL 科研语料
- **结构解析**：新增统一 `ScientificDocument`、JATS/TEI parser、GROBID REST 客户端与 `/scientific/parse`/documents API；保留 section/sentence/page/bbox/table-cell/formula/citation/page dimensions。workflow 对科研 XML 自动优先解析；PDF 检测 GROBID 可用后落结构 artifact，服务离线不伪造坐标。
- **GROBID 服务**：Colima 调为 6 CPU / 12GB，官方 `grobid/grobid:0.9.0-crf` 容器 `corpus2node-grobid` 已在 8070 健康运行；新增 `scripts/grobid.sh` 与 production compose 服务。full 镜像在 ARM64 无 manifest，未使用慢速 amd64 模拟。
- **N 元关系**：受控关系枚举；Claim/Experiment/MetricResult/Condition/Evidence 与 Method/Dataset/Baseline 显式 role links；`EVALUATED_ON`、`OUTPERFORMS`、`SUPPORTS` 强制必需角色。VDN/QMIX 真实报告 `ebcce80e-8444-4a99-86fb-1fbcb2ebd026` 产 3 experiments / 3 conditions / 16 grounded N-ary relations，类型含 EVALUATED_ON/OUTPERFORMS/REPORTS_RESULT/SUPPORTS。
- **MARL corpus**：完整读取 ICLR/ICML/NeurIPS 2024–2025 六届 21,224 条官方录用索引，形成 131 篇高召回候选（101 core + 30 adjacent review），131/131 有效 PDF；每个会议年度分层 5 篇，形成 30 篇 corpus。
- **真实批处理**：30/30 DeepSeek silver（错误 0）；30/30 GROBID 成功，912 sections / 12,589 sentences / 45,234 sentence bboxes / 152 tables / 7,237 cells / 1,707 formulas。silver 合计 431 entities / 376 relations / 166 中文 Claims / 74 numeric results / 143 locators，其中 141 带 bbox，5 个 table-cell locator。
- **评测纪律**：新增实体/关系/Claim/数值 PRF 与 locator strict/bbox IoU 指标、CLI、双审规范；30 个文件 schema/evidence 完整性通过、missing locator=0，但 status 仍为 silver。领域人工双审前正式分数故意不生成。
- **验证**：pytest **173 passed**；ruff clean；真实 GROBID、真实 DeepSeek、真实 PDF 全部跑通。

### 2026-07-12 — 科研证据图谱 MVP + VDN/QMIX 真实流程
- **本轮目标**：实现“原始科技文献 → 可核查科研证据图谱 → 跨论文发现 → R&D 决策卡”的客户垂直主线，并使用现有两篇多智能体强化学习论文和已配置 API Key 做真实测试。
- **已完成**：新增 scientific 独立契约、中文优先 prompts、论文级抽取与 evidence alias 校验、证据矩阵、跨论文综合、R&D 决策卡、JSON 方言归一化/重试/缓存/确定性兜底、artifact 存储与 CRUD API；前端新增 `/scientific` 客户页与顶部入口；通用 graph prompt 也改为中文解释字段 + 英文正式名/alias 分离。
- **真实验证**：VDN session `f206a0d4...` + QMIX session `945a6176...`，DeepSeek 真实调用；最终报告 `f1c88905-7d9f-4434-9780-978e94bcd238` 为 2/19/19/10/3/27/2/1（papers/entities/relations/claims/experiments/evidence/insights/decisions），claim 引用 11/11 全部能映射到真实 chunk，示例 locator 为 VDN PDF 原文段落 2。
- **工程验证**：`pytest -q` → **167 passed**；`ruff check src tests` → clean；`frontend npm run build` → 通过；重启本地后端后 `/health` 与 `/api/scientific` 均 200，最新报告含 2 insights / 1 decision。
- **已知边界**：当前 PDF 摄入的部分 Kimi 产物没有页码/bbox，locator 回退到“文件名 + 原文段落”；跨论文模型返回的不可验证证据会被过滤并采用明确的确定性综合兜底。下一阶段按 `docs/SCIENTIFIC_RD.md` 接 JATS/TEI/GROBID、表格单元格和 PDF bbox locator，并建立约 30 篇 gold corpus。

### 2026-07-10 (2) — 删除失败运行态修复 + 科研证据图谱方向
- **删除失败根因**：前端 Vite HMR 已加载本轮 DELETE 代码，后台 uvicorn 是 7 月 6 日启动的旧版本；运行 OpenAPI 无 DELETE 和 `/test` 路由，日志确认历史发现 DELETE 全部为 405。普通 `corpus restart` 因 pidfile 丢失无法接管旧进程。
- **处理**：用项目 `force-stop` 清理 8000/5173 未跟踪进程，再以 `corpus dev` 启动 reload/HMR；前端 `confirmDelete` 对 405 给出“后端仍是旧版本，请运行 corpus restart”提示。
- **真实验收**：创建临时 DiscoveryReport 和 CourseSession，经运行中 HTTP API 删除均 200 且 artifact 消失；浏览器创建第二个临时报告，点击历史删除 → 确认 → 条目 detached + “历史发现已删除” toast。临时数据已清净，用户原 4 条报告仍在。
- **科研方向**：新增 `docs/SCIENTIFIC_RD.md`，提出 Scientific Evidence Graph：科学文献身份/版本、JATS/TEI/GROBID 结构解析、typed scientific entities、document-level experiment relations、claim-evidence locator、跨论文证据矩阵/矛盾/研究空白/方法迁移与 R&D 决策卡；`CUSTOMIZATION.md` 将 scientific profile 列为首个推荐垂直包。
- **验证**：162 passed；ruff clean；前端 production build 通过；`git diff --check` 通过。
- **下一步**：选择一个领域和约 30 篇论文建立 gold corpus，再做 Phase 1，而不是直接接全网论文搜索。

### 2026-07-10 — 多客户定制策略 + 历史发现删除 + 水平测试迁移
- **本轮目标**：安排面向不同服务客户的定制版本开发方式；新增历史知识发现删除；将“试卷”全面调整为不选题型、按知识点重要度规划的水平测试。
- **已完成**：
  - 新增 `docs/CUSTOMIZATION.md`：确定“单产品核心 + 客户配置包 + 客户适配器 + 独立部署”，列出分层、目录、数据隔离、需求进入流程、测试矩阵和四阶段落地顺序。
  - 历史发现新增 artifact 删除、`DELETE /discovery/{id}`、前端历史条目删除按钮与不可撤销确认；删除当前报告同步关闭详情。
  - 新契约为 `TestDocument/TestQuestion/GenerateTestRequest`；新主接口 `/generate_test`、`/test/*`、导出 `/export/{id}/test/*`，新 artifact 为 `test.json`。旧 Exam Python 类型、`/exam` 路径和 `exam.json` 读取保留兼容，旧路径不出现在 OpenAPI。
  - 测试生成改为确定性先按 `importance_score` 选择主知识点（小图额外题优先重复 top half），LLM 只决定合适的题目形式；每题保存 `primary_concept_id` / `importance_score`，仍经独立 verifier 回路。
  - 前端移除题型选择，仅保留题数；标签、设置、导出、选区问答和文档均改称“测试/水平测试”，题卡展示知识点重要度与测试依据。
- **验证**：`.venv/bin/python -m pytest -q` → **162 passed**；`.venv/bin/ruff check src tests` clean；`frontend npm run build` 通过；OpenAPI 仅公开 test 主路径；旧 `exam_id` artifact 有迁移测试。
- **已知风险**：未调用真实 LLM 重跑测试，重要度计划的结构化服从度仍需用一个真实资料集浏览器验收；`Purpose.exam`、`exam/` 目录和旧路由仅作为内部/外部兼容层暂留。现有演示 PPTX/截图仍是迁移前画面，若继续用于销售演示需另行重拍/重建。
- **下一步最佳动作**：先收集两个真实客户的差异矩阵，再实现第一版 customer profile；不要只根据一个客户需求提前抽象。

### 2026-07-06 (3) — 产品演示套件（图文 + 幻灯片 + 台本，全自动产出）
- **产出**：`docs/demo/`——`DEMO.md`（六幕产品叙事 + 3–5 分钟现场台本表 + runbook）、10 张 playwright 实拍截图、`Corpus2Node-演示.pptx`（11 页 16:9，暖米白 #faf9f5 + 赭石橙 #bc6a3a，宋体标题/苹方正文；deck.js 附 repo 可重建）。两大卖点主线：可溯源可解释 + 全本地私有化。
- **演示数据（deepseek/kimi，全部落盘缓存，现场零生成）**：主秀库「Python 程序设计 / Python 基础与数据结构」重建于当前流水线（100 页 PDF → **87 概念 / 819 关系 / 7 社区**，session b4f59dff；旧 `python基础` 119/1816 是修复前产物，保留但不上镜）；chat 2 问带引用、notes 7 节、exam 6 题；发现「Reinforcement Learning · 4 提案」（VDN×QMIX + 意图，1 条已采纳 + 深挖五字段）与「递归×树×搜索」教学向副例；注册表加 ollama-本地凭据道具（绑定未动）。
- **顺手修的上镜缺陷（已提交代码）**：提案证据按文本前 80 字去重（chunk 重叠导致引文重复）；deep_dive 的 `**标签**` 前端渲染为粗体；proposer 失败/全灭时补 warning 日志（原来静默吞）。
- **QC**：slides_test 无溢出、detect_font 无缺字体；LibreOffice 渲染的手写体是代理替换假象，qlmanage 原生渲染确认宋体/苹方正确。pytest 159 · ruff · tsc · build 全绿。
- **注意**：前后端服务保持运行中（用户原本就开着，未动）；演示前跑一遍 DEMO.md 的 runbook 即可。

### 2026-07-06 (2) — 知识发现 v2：跨库创新提案（老板场景）+ 呈现图重做 + 生产模型文档
- **场景重定义**：各部门汇报 = 资料集/知识库，老板要的不是「概念对交叉」而是**可执行的跨部门创新提案**。发现流程升级为：宽召回 → judge 桥接点 → **proposer 合成提案**（intent 导向）→ 老板反馈回路（采纳/搁置持久化 + 避重）→ 单提案深挖成最小方案。
- **后端**：`InnovationProposal` 契约（title/pitch/combination/first_step/risks/status/deep_dive/sources/evidence）；`DiscoveryReport` += intent/proposals；proposer seam（Purpose.chat→critic 回退，无 LLM 用 relation_type 模板 fallback）；概念 grounding 防幻觉（引用名多键解析 + 跨集 ≥2 强制）；`PATCH /discovery/{id}/proposals/{pid}`（kept/discarded/new）+ `POST …/deepen`（五字段结构化 → markdown）；`_avoid_titles` 用历史反馈避重。
- **json_mode 教训（重要）**：ollama/openai 的 json_mode 不带服务端 schema 锁定，**prompt 必须内嵌字段形状示例**（`_PROPOSAL_FORMAT_HINT`/`_DEEPEN_FORMAT_HINT`），否则小模型返回空字段/自造结构（gemma4 实测 deepen 空 plan、draft 全灭）。judge/extract 一直带 hint 所以没踩过。
- **grounding 两个实修**：模型引用概念会带 prompt 显示后缀（`互斥锁（资料集名）`）→ raw+去括号多键映射；两集同名概念撞键 → 一键多参与者列表 + **解析时优先未覆盖资料集**（否则跨集校验永假）。
- **前端**：发现统一走 `DiscoveryLaunchModal`（含意图输入）；报告面板提案卡优先（采纳/搁置/深挖，状态同步历史）；**BridgeGraphView 重做**：提案报告用 部门→桥接概念→提案 三列（采纳 ring 高亮/搁置降透明/点击定位卡片），旧报告自动保留 finding 布局。
- **本机离线实测**（gemma4:e2b + bge-m3，两个 OS 语料库）：run 39s 产 4 条 **LLM 提案全部跨集**（如「跨系统资源同步机制：统一资源调度层接口，对比 Mutex/Semaphore 负载差异」）；PATCH kept ✓；deepen 6.6s 出五字段方案 ✓；无 LLM fallback 路径 ✓。
- **同轮完成**：`docs/DEPLOYMENT_MODELS.md`（生产开源模型三档推荐：单模型全包 Qwen3-VL-32B / 甜点 Qwen3.5-35B-A3B / 旗舰 DeepSeek-V4-Flash + vLLM 参数与注册表绑定表）；上一轮遗留全部入库（critic grounding 修复 20ebc2a、Docker deploy 栈 96d39b1、docs ed2394d）。
- **验证**：pytest **159 passed**（discovery 17 条，+6 新增）· ruff clean · tsc + vite build ✅。
- **待办**：浏览器实测提案交互手感；深挖按钮可考虑流式；`_PROPOSAL_TARGET`/深挖字段可再按真实使用调。

### 2026-07-06 — 全离线 LLM 方案（Ollama / LM Studio provider + 本机 E2E 实测）
- **需求**：全离线处理；参照 obsidian-copilot 的 provider 设计（Ollama 走原生客户端管 `num_ctx`，LM Studio 走 OpenAI 兼容 + dummy key）；本机小模型全流程实测速度与并发。
- **后端**：kind += `ollama`/`lmstudio`（默认端点、免密钥、凭据级 `num_ctx`/`max_concurrency`）；`build_chat_model`：ollama→ChatOllama（`num_ctx` 默认 8192、`reasoning=False`）、lmstudio→openai 路径；`credential_params` 对本地 kind 归一（补 /v1 + dummy key）供 vision/embedding 的 SDK 复用；`structured_output_method`：**ollama=json_mode**（实测 gemma4 在 json_schema 语法锁定下 relations 塌缩为 []）、lmstudio=json_schema；`concurrency_for` 接入 workflow 的 extract/critic 并发。
- **Embedding**：注册表 `embedding` 用途绑 ollama kind→`OllamaEmbeddings` 原生批量；其余 `OpenAIEmbeddings` 且非官方端点自动 `check_embedding_ctx_length=False`（默认 tiktoken token 数组会被本地/DeepSeek 端点 400）。
- **摄入离线化**：新增 `ingest/pdf_local.py`（pypdf 文本层逐页块，保页码 locator；扫描件报错指向 Kimi OCR）；`kimi_client.vision_is_moonshot()` 门控 Moonshot 专属（file-extract / `ms://` 视频上传 / K2.6 关思考参数）；视频非 moonshot 回退 faster-whisper 转写音轨；图片可绑本地 VLM（base64 image_url 同路径）。
- **抽取修复（确定性，云端模型同益）**：`extract.merge_results` 末尾 `_reconcile_relation_endpoints`——关系端点经概念 name/canonical/别名映射归一，修复「小模型端点写表面名（平衡树）而概念 canonical 是英文（balanced tree）→ 关系悬空被 critic 全丢」。
- **API/前端**：`POST /settings/llm/models` 枚举端点模型（ollama 走 `/api/tags`，其余 `{base}/models`；失败返回 `error` 字符串降级为提示）；SettingsPanel：kind 四选、base_url 按 kind 预填、本地免密钥标注、「读取模型」按钮 + datalist、ollama 显示 `num_ctx`、本地显示并发上限。
- **本机 E2E**（Apple M3 / 24GB；Ollama 0.20.7→**0.31.1**（gemma4 需 ≥0.30.5）；`OLLAMA_NUM_PARALLEL=4`；模型 `gemma4:e2b-it-qat` 4.3GB（vision+tools+thinking）+ `bge-m3` 嵌入 + `llama3.1:8b` 参照；隔离存储、真 HTTP 驱动）：
  - 全流程 ✅：workflow（ingest→extract→critic→build）、chat agent（工具调用 + 引用 + 语料外问题诚实拒答）、exam 4 题 verifier 回路、models 端点、bge-m3 嵌入检索。
  - **速度三板斧**：`reasoning=False` 实测 ~**5×**（22.7s→4.7s 同批任务）；抽取类绑定 `temperature=0.2` 抑制小模型方差（默认 1.0 时同语料 22→1 概念级波动）；并发 42-chunk 语料 extract **c=1 631s → c=4 397s（1.6×**，Metal iGPU 计算受限非线性）。
  - 模型建议：`gemma4:e2b-it-qat` 最小最快全能力；`llama3.1:8b` critic 裁决更稳（gemma4 judge 输出偶尔过不了 GraphCriticReport 校验→仅确定性修复兜底）；追求抽取一致性上 12b 级。
- **验证**：pytest **153 passed**（+18）、ruff clean、`tsc --noEmit` + `npm run build` ✅。新依赖：`langchain-ollama==1.1.0`、`pypdf`（均 core）。
- **待办**：LM Studio 本机未装（与 openai kind 同一 ChatOpenAI 路径，已单测覆盖；装后冒烟即可）；绑定 UI 暂未暴露 per-binding temperature（离线建库建议手动把 graph/critic/exam 绑定 temperature 设 0.2，本轮 E2E 经 API 设置）。

### 2026-06-27 — 首页拖拽排序（知识库 + 资料集）
- **本轮目标**：首页支持手动拖拽给知识库（分组）和资料集（组内）排序，覆盖当前的 updated_at 排序。
- **已完成（纯前端，无后端/契约改动）**：原生 HTML5 DnD + 抓手图标 `GripIcon`；知识库分组头与资料集行各加抓手（仅抓手 `draggable`，避免与折叠/导航点击冲突）；`applyOrder` 稳定排序工具（不在顺序表里的项保持 updated_at）；顺序持久化到 localStorage（`c2n:courseOrder` string[] / `c2n:sessionOrder` Record<course, id[]>），与既有 `collapsedCourses` 同模式；落点高亮 `inset 0 2px 0 accent`；每次 drop 持久化**完整**顺序列表（之后稳定，新项追加到末尾）；资料集仅在**同知识库内**排序（跨库 drop 被 guard 拦截）；知识库改名时同步迁移 courseOrder/sessionOrder 的 key。
- **运行过的验证**：前端 `npx tsc --noEmit` + `npm run build` 通过；后端未改，`pytest -q` → **135 passed**、`ruff` clean。
- **已知风险或未解决问题**：顺序存 localStorage（不跨设备/不入库，符合 UI 偏好定位，与折叠状态一致）；删除的库/资料集 id 会留在顺序表里（applyOrder 忽略缺失项，无害，未清理）；把「知识库」拖到资料集行上是无效 drop（落点须是另一个分组头），course 拖拽会丢失需重做（轻微）。
- **下一步最佳动作**：浏览器 `corpus dev` 实测拖拽手感（分组与组内）；其余回到 eval baseline / Step 7。

### 2026-06-27 — 发现标题（LLM 命名）+ 合并发现按钮 + 去掉新增资料集按钮
- **本轮目标**：(1) 历史发现用随机 id 命名 → 让 LLM 自动生成简短标题，并给现有两条补标题；(2) 把「知识发现」「随机发现」两个按钮合一（选了资料集就对选中发现，没选则弹确认问是否随机）；(3) 删掉首页知识库分组里的「新增资料集」按钮（与「新建知识库」功能重复）。
- **已完成**：
  - **后端标题**：`DiscoveryReport.title` 新字段；`engine` 加 `_make_titler_or_none`（Purpose.critic 结构化输出 `DiscoveryTitle`）+ `_title_for`（清洗书名号/标点、≤24 字）+ 确定性 `derive_title`（top finding 两个概念名 `A × B 等 N 处`，去括号/防截断悬尾）；`run_discovery` 加 `titler` seam，无凭据/失败回退确定性。
  - **回填**：用 `derive_title` 给现有 2 条报告补标题（`a0211ce3 → Reinforcement Learning`、`52e0ff04 → 递归基准情况 × 有序列表 等 8 处`）。
  - **前端**：`ConfirmModal` 泛化（`confirmLabel/loadingLabel/tone`）；两按钮合一为「知识发现」（`startDiscovery`：有选中→selected，无选中→`randomConfirm` 弹确认→random）；删 `group-add-btn`；历史条目 + 报告面板头显示 `title`（mono→ui 字体、省略号）。
- **运行过的验证**：`.venv/bin/python -m pytest -q` → **135 passed**（含 2 个新 titler 测试：注入 titler 清洗标点、无 titler 回退确定性）；`ruff` clean；前端 `tsc --noEmit` + `npm run build` 通过。
- **已知风险或未解决问题**：现有 2 条是**确定性**标题（非 LLM），如要 LLM 命名需重跑发现或单独 backfill（耗 token）；标题 LLM 调用绑 Purpose.critic（→ graph 回退），无凭据时静默用确定性。
- **下一步最佳动作**：浏览器确认合并按钮 + 随机确认弹窗 + 历史标题观感；其余回到 eval baseline / Step 7。

### 2026-06-27 — mixed 多模态抽取过少修复
- **本轮目标**：用户反馈 `06 mixed` 同时输入文档和图片，但最终概念非常少；要求定位问题并排查其他模态是否有类似风险。
- **核查结论**：`06 mixed` 的上传和摄入均正常：图片 1 chunk（454 字）+ PDF 40 chunks（33774 字），extract 真实抽到 84 concepts / 60 relations；最终只剩 1 concept 的根因在 `graph/critic.py`：grounding snippets 只靠 embedding 检索，许多明明在原文出现的概念被提示为“未检索到相关片段”；同时 `apply_repair` 只保护“全部删光”，未保护“84 个删 83 个”的近清空场景。
- **已完成修复**：`_grounding_snippets` 先做字面命中（含 `_`→空格变体、过滤过短词、英文边界）再用 embedding 补充；未命中提示改为“检索器未命中不是否定证据”；`apply_repair` 增加近清空保护，避免过度激进的 critic 删除绝大多数概念。
- **其它模态排查**：现有 artifact 中 image/audio 单模态曾出现 critic 全部判 ungrounded，但旧保护刚好拦住；PDF/Word/PPT/Video 有不同程度裁剪但未近清空。新保护对所有模态统一生效。
- **运行过的验证**：`.venv/bin/python -m pytest tests/test_critic.py -q` → 8 passed；`.venv/bin/python -m pytest -q` → **135 passed**；`.venv/bin/ruff check src tests` → clean。用 `06 mixed` 旧 artifact 无外部调用复核：新 grounding 可为 55/84 个旧 verdict 概念找到原文片段。
- **已知风险或未解决问题**：当前旧的 `06 mixed` graph artifact 仍是 1 concept；要让 UI 显示修复后的图谱，需要用户确认后重新跑该 session 的 workflow（会消耗真实 LLM token，并覆盖该 session 的 graph/candidates/run artifact）。

### 2026-06-26 — audio 专项复核
- **本轮目标**：用户反馈 VDN 已成功，要求专心处理 audio。
- **核查结论**：纯音频 `.mp3` 路径正常，`Test: Modality / 03 audio` 的 `BV1m2P9zsEgW.mp3` 已是 `graph_ready`，ingest artifact 为 `source_kind=audio`，共 6 个 chunk。标题为 `05 audio` 的失败样本实际上传文件是 `.mp4`，后端按扩展名正确识别为 `video`，不走 faster-whisper。
- **真实验证**：直接调用当前 `describe_video()` 处理 26MB `.mp4` 成功返回约 3400 字视频内容；随后跑完整 `run_workflow(6c1a004f...)` 成功，session 变为 `graph_ready`，图谱为 5 chunks / 7 concepts / 9 relations / 2 clusters。
- **额外确认**：当前服务状态正常（backend `http://127.0.0.1:8000`，frontend `http://localhost:5173`）；`01 VDN` 也已是 `graph_ready`（68 chunks / 43 concepts / 118 edges / 10 clusters）。
- **已知风险或未解决问题**：`.mp4` 课件标题叫 audio 容易误导；系统按文件扩展名路由，`.mp4` 永远是 video，纯 `.mp3/.wav/.m4a/...` 才是 audio。如果后续希望“只抽 mp4 音轨走 ASR”，需要新增一个显式模式，而不是复用当前 video 路径。

### 2026-06-26 — LLM 配置统一进注册表（Kimi/embedding 进 UI）+ 设置面板重构
- **本轮目标**：(1) 配置混乱（.env 与 UI 两处、.env/.env.example 格式不一）；(2) 设置改为「凭据和模型一起选，下面直接绑」。用户选「Kimi + embedding 都进 UI」。
- **已完成**：
  - **purpose 扩到 6 个**：`Purpose` 加 `vision`（Kimi 图片/PDF/视频）+ `embedding`（远程嵌入）；`factory.credential_params()` 给非 chat 客户端取 (base_url/api_key/model/timeout)；`purpose_available()`。
  - **Kimi 进注册表**：新增 `ingest/kimi_client.vision_client()`，`pdf_kimi`/`image_kimi`/`video_kimi` 都从 `vision` 用途解析（不再 `settings.kimi_*`）；保留用户本轮的视频 Files API 上传（`ms://`）。
  - **embedding 进注册表**：`index/embeddings` 的 openai_compatible 从 `embedding` 用途解析。
  - **config.py 去 LLM 凭据**：删 `kimi_*`/`embedding_{base_url,api_key,model}`；`kimi_timeout_seconds`→`vision_timeout_seconds`。
  - **store 种子 + 迁移**：bootstrap 额外种 Kimi(vision)/embedding；`_ensure_vision_binding` 把老注册表里 Kimi 凭据自动绑 vision（已对用户真实注册表确认会绑到 `kimi`）。
  - **设置面板重构**：凭据=端点+密钥+模型（模型必填）；用途单选下拉「凭据·模型」直接绑（去掉每用途的 model 输入框）；加 vision/embedding；去掉「.env 配置」提示；`web/index.html` 同步。
  - **.env 清理**：`.env.example` 重写为「模型凭据在 UI + 基础设施/首次种子」；`.env` 用脚本对齐为干净 `KEY=value`（无行内注释，避免 dotenv 把注释当值——曾导致 `API_AUTH_TOKEN` 误置触发 401）；`.gitignore` 改 `.env*` + `!.env.example`（`.env.bak` 备份不入库）。
- **运行过的验证**：`pytest -q` → **131 passed**；`ruff` clean；前端 `tsc --noEmit` + `npm run build` 通过。
- **新增测试证据**：`test_llm_layer`（credential_params vision / 缺用途报错 / load 自动绑 vision）；`test_adapters`（image 无 vision 绑定报错 / video 用注册表凭据走 Files API 上传）。
- **已知风险或未解决问题**：踩坑——`.env` 行内注释会被 dotenv 当值（已改为无行内注释）；老注册表迁移在下次后端启动时写入 vision 绑定（幂等）；`.env.bak` 含旧密钥（已 gitignore，可删）；测试仍隐式依赖真实 `.env` 的 `API_AUTH_TOKEN` 为空（既有耦合）。
- **下一步最佳动作**：用户重启后端确认 vision 自动绑 Kimi、图片/PDF/视频可建图；如要 commit 本轮可一起提（含用户的视频 Files API 改动 + UI 标签）。


### 2026-06-26 — 视频 mp4 摄入连接错误修复
- **本轮目标**：用户最新音频/视频测试上传 26MB `.mp4`，workflow ingest 阶段报 `Connection error.` / `Request timed out.`；用户确认 Kimi 支持 mp4，要求排查。
- **根因**：失败文件实际按 `.mp4` 路由到 `video_kimi.describe_video`（不是 audio/faster-whisper）。旧实现把整个 mp4 base64 内联到 chat request；26MB 视频膨胀到约 35MB JSON，再经过本机代理，日志显示 `Broken pipe` / `ReadTimeout`。Kimi 官方文档确认支持 mp4，也明确大视频应使用 Files API 上传，`purpose="video"` 后再走 vision 理解。
- **已完成**：`video_kimi.py` 改为先 `client.files.create(..., purpose="video")` 上传视频，再在 chat content 中传 `video_url: {"url": "ms://<file_id>"}`；视频请求 timeout 提到至少 600s；完成后 best-effort 删除远端临时文件；删除旧 base64 路径。
- **运行过的验证**：`tests/test_adapters.py` 新增无网络 fake OpenAI 测试，断言 `.mp4` 走 Files API `purpose=video` 且 chat 中使用 `ms://file_id`；`.venv/bin/python -m pytest tests/test_adapters.py -q` → 12 passed；`.venv/bin/python -m pytest -q` → **128 passed**；`.venv/bin/ruff check src tests` → clean。
- **已知风险或未解决问题**：没有直接用用户真实 26MB mp4 再跑 Kimi，因为会调用外部 API/消耗额度；若仍超时，下一步应考虑在本地按时长切片后分段上传/总结，而不是回退 base64。

### 2026-06-26 — 音频摄入修复（Kimi API 无音频 → faster-whisper 转 core）
- **本轮目标**：音频建图失败报 `needs faster-whisper — run uv sync --extra audio`；用户认为已配 Kimi（有音视频能力）不该再走 whisper。
- **查证（官方文档）**：Kimi/Moonshot **平台 API 只接受 text/image/video，不接受音频输入**（无 `input_audio`/`audio_url`，无转写端点）；`Kimi-Audio` 是另一个需自托管的开源 7B 模型，不在平台 API 上。故音频**无云端路径**，必须本地转写——用户前提是误解（Kimi 消费端语音 ≠ 平台 API）。
- **已完成**：`faster-whisper` 从 `[audio]` extra **提升为 core 依赖**（torch-free，与 docx/pptx/yaml 同级），删除 `audio` extra；`uv sync` 安装（faster-whisper 1.2.1 + ctranslate2/av/onnxruntime，无 torch）；`audio_whisper.py` 文档与报错信息改为「本地转写 / Kimi 不支持音频 / `uv sync` 即可」；端到端本机实测（合成 WAV 跑通 CTranslate2+PyAV+onnxruntime，3.1s）。
- **运行过的验证**：合成音频 e2e 跑通；`pytest -q` → **127 passed**（原 126 → 去掉一个仅在「未装 whisper」时才跑的 skip 测试、改写为「依赖已 bundle」+「缺失时报错清晰」两测）；`ruff` clean。
- **新增/改测试证据**：`tests/test_adapters.py::test_audio_dependency_is_bundled`、`test_audio_error_is_clear_if_transcriber_missing`（monkeypatch `sys.modules["faster_whisper"]=None` 强制 ImportError，断言报错含 "locally"）。
- **已知风险或未解决问题**：core 安装体积略增（ctranslate2/av/onnxruntime，但无 torch）；whisper 首次转写下载 `base` 模型(~140MB)；若用户更想要云端 ASR，需另加一个支持 `/audio/transcriptions` 的 OpenAI-compatible 凭据（当前 DeepSeek/Kimi 都不转写）——本轮未建该路径（无可用凭据、避免投机）。
- **下一步最佳动作**：用户用真实音频建一次图确认转写质量；如需云端 ASR 再议。

### 2026-06-26 — 流水线阶段卡片瘦身（5→4 一行）
- **本轮目标**：用户反馈流水线阶段图丑（5 张卡片在 `repeat(4,1fr)` 网格里换行 + 大片空白）；去掉「质检修复」卡片让四个一行。
- **已完成**：`PipelinePage.tsx` 的 `STAGES` 去掉「质检修复」（critic 仍在后端跑，进度折叠进「构建图谱」，文案补「质检修复 + 建立关系网络」）；phase 重映射 critic `setPhase(4)→3`、done `setPhase(5)→4`；CSS 无需改（本就 `repeat(4,1fr)`）。run-metrics 面板仍单列 `critic` 节点，观测不丢。
- **运行过的验证**：`cd frontend && npm run build`（`tsc && vite build`）→ 通过，无 TS 错误。后端未改，126 passed 不受影响。
- **已知风险或未解决问题**：无。canvas 透明度阈值用 `phase>=0/1/2/3`，对新 phase 序列（0→2→3→4）仍单调递进，无回归。
- **下一步最佳动作**：用户在浏览器确认四阶段一行观感；回到 eval baseline / Step 7。

### 2026-06-26 — 知识发现增强（桥接图可视化 / 可溯源跳转 / 质量 / 历史）
- **本轮目标**：用户修了若干 bug 并新增知识发现功能；本轮在其基础上做四个方向的提升（用户多选确认）。
- **已完成**：
  - **质量增强（`discovery/engine.py`）**：`RELATION_TYPES` 8 类枚举 + `JudgedFinding` `field_validator` 把中文/越界值回填到枚举（前端 label 永远可解析）；证据 `_evidence_for` 每侧 top-2 并交错；新增 `_neighbor_index`/`_struct_terms` 结构化信号（共享图谱邻居/标签）并入候选评分；judge 候选池超过 `_JUDGE_BATCH=12` 时 `_run_judge` 分批 `asyncio.gather` 并发并按 confidence 合并；`_relation_type_for`/`_novelty_for` 算法版关系类型与新颖度重算。
  - **可视化**：新增 `frontend/src/components/discovery/BridgeGraphView.tsx`（ReactFlow 三列：发现→知识点→资料集），**懒加载**成独立 chunk，首页主包 376KB→229KB。
  - **可溯源跳转**：发现卡片概念 chip / 证据块、桥接图概念节点点击 → `/session/{id}?concept=`（复用全局搜索模式）。
  - **历史面板**：首页 `DiscoveryHistoryBar` 列出历史报告，点开重载；`storage/local.list_discovery_reports` 改按 `generated_at` 倒序。
- **运行过的验证**：`.venv/bin/python -m pytest -q` → **126 passed**；`.venv/bin/ruff check src tests` → clean；`cd frontend && npm run build` → 通过（BridgeGraphView 独立 chunk 2.4KB）。
- **新增测试证据**：`tests/test_discovery.py` 增 3 例——`relation_type` 枚举回填、judge 大池分批合并（含中文关系回填）、证据每侧多 chunk。
- **已知风险或未解决问题**：算法版关系类型/novelty 是启发式，真实 judge 质量仍需用户凭据实测；`listDiscoveries()` 当前拉全量 `DiscoveryReport`（含 bridge graph），库很大时宜加 summary 端点；证据 blockquote 点击未做键盘可达（chip 是 button 已可达）。
- **下一步最佳动作**：用户在浏览器跑一次真实发现，确认桥接图/跳转/历史观感；若要 commit，本轮发现功能（用户基线 + 本轮增强）仍全在工作树未提交。

### 2026-06-26 — 知识发现 + artifact 保存
- **本轮目标**：新增对选中资料集/随机资料集的知识发现功能，并做到发现结果 artifact 保存、测试完善。
- **已完成**：
  - 新增 `DiscoveryReport` 契约与 `DiscoveryRequest`；报告包含 findings、participants、evidence、score_components 和 bridge_graph。
  - 新增 `discovery/engine.py`：按选中或随机资料集加载已建图谱，生成宽候选；支持注入 AI judge seam，真实运行时尝试 `Purpose.critic` 结构化判断，失败或无凭据时退回算法版发现。
  - 新增 artifact 存储：`storage/local.py` 保存/读取/列出 `artifacts/discoveries/{discovery_id}.json`。
  - 新增 API：`POST /discovery/run` 运行并保存，`GET /discovery/{id}` 读取，`GET /discovery` 列出。
  - 首页新增资料集复选、多选知识发现、随机发现、结果卡片与 artifact id 展示；随机发现未选择资料集时由后端从全部真实已建图资料集中抽样。
- **运行过的验证**：`.venv/bin/python -m pytest -q` → **123 passed**；`.venv/bin/ruff check src tests` → clean；`cd frontend && npm run build` → 通过。
- **新增测试证据**：`tests/test_discovery.py` 覆盖算法版发现、AI judge seam、API 保存/读取/list artifact、随机发现、空选择拒绝、虚拟总图谱过滤。
- **已知风险或未解决问题**：真实 LLM judge 质量需用户凭据/token 在浏览器实测；首版发现报告已落盘但没有历史列表 UI，只展示本次运行结果。

### 2026-06-25 — 资料集 / 知识库重命名
- **本轮目标**：增加资料集改名与知识库改名功能。
- **已完成**：
  - 后端新增 `PATCH /sessions/{session_id}`，只更新当前资料集的 `lecture_title`，并刷新 `updated_at`。
  - 后端新增 `PATCH /sessions/course/rename`，按旧 `course_title` 批量改名；同步虚拟总图谱 session 的 `[总图谱] ...` 标题；拒绝空标题、过长标题和改到已有知识库名。
  - 前端首页知识库分组头新增重命名按钮；资料集行新增重命名按钮；保存后本地列表、知识库筛选器、折叠状态即时同步。
  - 保持 wire 契约不变：仍沿用 `course_title` 表示知识库、`lecture_title` 表示资料集；没有执行 Course→Corpus 大重命名。
- **运行过的验证**：`.venv/bin/python -m pytest -q` → **117 passed**；`.venv/bin/ruff check src tests` → clean；`cd frontend && npm run build` → 通过。
- **已知风险或未解决问题**：重命名只更新 session 元数据；已生成笔记/试卷内部标题不自动重写，避免改动用户生成内容。

### 2026-06-25 — 全面修复项目审阅问题（主要 + 次要）
- **本轮目标**：按项目全面审阅结论修复主要/次要问题；README 暂时清空；所有相关修改写入 docs；允许提交。
- **已完成**：
  - API 安全：新增 `APP_ENV` / `DEBUG_TRACEBACKS` / `CORS_ALLOW_ORIGINS` / `API_AUTH_TOKEN` / `MAX_UPLOAD_BYTES` 配置；生产环境不返回 traceback；配置 token 后非公开 API 需 Bearer token。
  - 上传安全：上传文件名清洗为 basename；磁盘文件按 `source_id + ext` 存储；分块读取并限制大小；空文件/超限文件拒绝；避免同名覆盖与路径穿越。
  - 落盘一致性：JSON artifact、LLM settings、prompt settings、workflow run artifact、graph candidates/critic report 改为同目录临时文件 + `os.replace` 原子写。
  - workflow 一致性：流式 workflow 完成和缓存路径都回填/返回真实 `chunk_count`。
  - chat 质量：传入最近 12 条历史消息；生成前做确定性预检索并把可引用资料放入当前问题；模型漏写 `[n]` 时补 `参考来源`；流式失败不再落盘空 assistant 消息。
  - notes/exam 流式任务：同一 session 同一参数复用任务，不同参数并发请求返回 409，避免拿到错误结果；完成任务缓存加上限清理。
  - 前端行为：命令面板按 session 状态跳 workspace/pipeline 并隐藏虚拟总图谱；上传页全部失败时停留并提示，部分成功才进入 pipeline；前端包名改为 `corpus2node-frontend`。
  - 启动脚本：`corpus stop` 只停 pidfile 记录进程，新增 `corpus force-stop` 显式清端口，避免误杀其他项目。
  - CI / 文档 / 清理：新增 GitHub Actions 最小 CI；README 按要求清空；`.env.example` 增加新增安全/上传配置；清理多模态摄入陈旧注释。
- **运行过的验证**：`.venv/bin/python -m pytest -q` → **112 passed**（1.7s）；`.venv/bin/ruff check src tests` → clean；`cd frontend && npm run build` → 通过。
- **新增/更新测试证据**：上传路径清洗与超限拒绝；可选 API token 与生产错误隐藏；流式 workflow `chunk_count`；chat 引用补齐与历史注入；jobs 异参数冲突。
- **提交记录**：本轮修复已提交为最新 `fix: harden app flows after project review`。
- **已知风险或未解决问题**：真实 LLM 端到端和 eval baseline 仍需用户凭据/token；全局概念搜索仍是子串匹配；README 当前故意为空。
- **下一步最佳动作**：跑真实小语料 baseline；或进入 Step 7 的 Course→Corpus 契约重命名 / 持久化向量库 / Docker。

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
