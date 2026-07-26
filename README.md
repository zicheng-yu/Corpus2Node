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

打开 `http://localhost:5173`。默认 `AUTH_MODE=legacy_token`，本地仍可零配置使用；也可将 `AUTH_MODE=accounts` 后用 SQLite 验证个人账号流程。账号模式默认 `ACCOUNT_PRODUCT_MODE=personal`：每个账号拥有独立资料库、提示偏好与模型 API 配置。

首次启用账号模式时生成首个账号激活链接：

```bash
uv run corpus2node-admin bootstrap-admin --email admin@example.com
```

后续账号由服务器运营者生成独立激活链接，不通过团队邀请：

```bash
uv run corpus2node-admin invite-user --email user@example.com --name 'User'
```

本地 BGE-M3 embedding 需要额外安装重依赖：

```bash
uv sync --extra ml
```

## 主要能力

- 通用资料：上传后运行建图流程，在工作区检索、浏览图谱、对话、生成笔记与测试。
- 科研证据：在“科研证据图谱”中可直接选择已上传论文；系统只执行所需摄入，不要求先建通用图谱。PDF 的 GROBID 结构解析只在科研路径触发。
- 知识发现：对多个已建图资料集生成跨库联系与可追溯提案。
- 个人账号：每个账号使用不可切换的私有资料库；模型凭据按用户独立保存并只返回掩码，其他账号不可读取或调用。
- 套餐与分享：Free / Team Beta 权益、用量记录和只读降级；可创建固定报告的安全只读外链。团队协作底层保留为后续客户版本，当前产品不展示团队、成员或平台管理界面。
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

生产栈使用 PostgreSQL、Alembic 和 `AUTH_MODE=accounts`，默认只监听本机 `127.0.0.1:8080`。Cookie 标记为 Secure，因此远程访问必须配置 HTTPS 反向代理。

```bash
export POSTGRES_PASSWORD='replace-with-a-long-random-secret'
export PUBLIC_APP_URL='https://corpus.example.com'
docker compose -f deploy/docker-compose.yml up -d --build
docker compose -f deploy/docker-compose.yml exec backend \
  corpus2node-admin bootstrap-admin --email admin@example.com
```

启动脚本会先执行数据库迁移，再启动 API。激活首个账号后，可用 `corpus2node-admin invite-user` 为其他用户生成独立激活链接。上线已有数据前先备份 `artifacts/`，再用 `corpus2node-admin migrate-artifacts` dry-run 核对，确认后加 `--apply`；迁移只登记索引，不移动或覆盖原文件。完整流程见 `deploy/README.md`。

## 项目文档

- 稳定架构与决策：`AGENTS.md`
- 当前进度与功能映射：`docs/PROGRESS.md`
- 会话交接：`docs/SESSION.md`
