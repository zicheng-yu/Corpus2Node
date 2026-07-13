# Corpus2Node

把 PDF、文档、图片、音视频等资料转换成可探索、可溯源的知识图谱，并在图谱与原文 chunk 上完成问答、笔记、测试、跨库发现和科技文献证据分析。

核心架构是两条分离的路径：离线 LangGraph workflow 负责 `ingest -> extract -> critic -> build`，在线 LangChain agent 通过确定性检索工具回答问题。中心性、社区发现、实体合并、共现边和布局等算法不交给 LLM。

## 本地启动

要求 Python 3.12、uv 0.10.x、Node.js 22。

```bash
uv sync --dev
uv run uvicorn corpus2node.api.app:app --reload --port 8000
```

另开终端启动前端：

```bash
cd frontend
npm ci
npm run dev
```

打开 `http://localhost:5173`。首次使用时在“设置 -> 模型设置”添加凭据并绑定 `graph`、`chat`、`critic`、`exam` 等用途；本地 Ollama / LM Studio 可不填 API key。

本地 BGE-M3 embedding 需要额外安装重依赖：

```bash
uv sync --extra ml
```

## 主要能力

- 通用资料：上传后运行建图流程，在工作区检索、浏览图谱、对话、生成笔记与测试。
- 科研证据：在“科研证据图谱”中可直接选择已上传论文；系统只执行所需摄入，不要求先建通用图谱。PDF 的 GROBID 结构解析只在科研路径触发。
- 知识发现：对多个已建图资料集生成跨库联系与可追溯提案。
- 可复现 artifact：业务事实写入 `artifacts/`；图谱保存来源 hash、模型、prompt、schema 与 embedding 指纹，输入或配置变化会自动使缓存失效。

## 验证

```bash
uv run ruff check src tests scripts
uv run pytest -q

cd frontend
npm test
npm run generate:api
npm run build
npm audit --audit-level=high
```

`docs/openapi.json` 与 `frontend/src/types/api.generated.ts` 是自动生成的契约快照。修改 API 后运行：

```bash
uv run python scripts/export_openapi.py
cd frontend && npm run generate:api
```

## Docker 部署

生产配置强制 Bearer token，且默认只监听本机 `127.0.0.1:8080`。远程访问请在前面配置 HTTPS 反向代理。

```bash
export API_AUTH_TOKEN='replace-with-a-long-random-secret'
docker compose -f deploy/docker-compose.yml up -d --build
```

浏览器端在“设置 -> 访问安全”保存同一 token。GROBID 和后端均不直接暴露宿主端口。Vercel 配置仅用于显式启用的临时预览，`/tmp` artifact 不具备持久性，不应当作生产部署。

## 项目文档

- 稳定架构与决策：`AGENTS.md`
- 当前进度与功能映射：`docs/PROGRESS.md`
- 会话交接：`docs/SESSION.md`
