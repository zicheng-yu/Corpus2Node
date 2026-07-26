# Corpus2Node 托管部署

生产栈由 PostgreSQL、私有 FastAPI、GROBID 和对外 nginx 组成。nginx 提供 React SPA，并将 `/api/*` 转发到后端；宿主机默认只监听 `127.0.0.1:8080`，外层必须配置 HTTPS。

```text
browser -> HTTPS proxy -> nginx -> backend -> PostgreSQL
                              |-> GROBID
```

## 首次部署

准备持久化目录并设置部署变量：

```bash
mkdir -p artifacts
export POSTGRES_PASSWORD='replace-with-a-long-random-secret'
export PUBLIC_APP_URL='https://corpus.example.com'
docker compose -f deploy/docker-compose.yml up -d --build
```

`deploy/start-backend.sh` 会先执行 `alembic upgrade head`，成功后才启动 API。确认服务：

```bash
docker compose -f deploy/docker-compose.yml ps
curl -fsS http://127.0.0.1:8080/api/health
```

随后生成首个账号激活链接：

```bash
docker compose -f deploy/docker-compose.yml exec backend \
  corpus2node-admin bootstrap-admin --email admin@example.com
```

复制输出链接完成激活。后续用户通过运维 CLI 获得各自独立的账号和私有资料库：

```bash
docker compose -f deploy/docker-compose.yml exec backend \
  corpus2node-admin invite-user --email user@example.com --name 'User'
```

## 导入已有 artifact

先备份 `artifacts/` 和数据库。迁移只新增 PostgreSQL 资源索引，不移动、覆盖或删除 JSON 文件：

```bash
docker compose -f deploy/docker-compose.yml exec backend \
  corpus2node-admin migrate-artifacts --organization-name 'Imported Workspace'
docker compose -f deploy/docker-compose.yml exec backend \
  corpus2node-admin migrate-artifacts --organization-name 'Imported Workspace' --apply
```

第一条命令是 dry-run，应先核对数量与 SHA-256 摘要；确认后再执行 `--apply`。旧 session 按 `course_title` 映射为稳定 Project。

## 更新、备份与回滚

更新前同时备份 PostgreSQL 和 `artifacts/`：

```bash
docker compose -f deploy/docker-compose.yml exec -T postgres \
  pg_dump -U corpus2node corpus2node > corpus2node.sql
tar -czf corpus2node-artifacts.tar.gz artifacts
docker compose -f deploy/docker-compose.yml up -d --build
```

常用运维命令：

```bash
docker compose -f deploy/docker-compose.yml logs -f backend
docker compose -f deploy/docker-compose.yml restart
docker compose -f deploy/docker-compose.yml down
```

数据库卷和宿主机 `artifacts/` 不会随普通 `down` 删除；不要执行 `down -v`，除非已经确认备份并明确要删除数据库。

## 安全边界

- 生产固定 `AUTH_MODE=accounts`、`DATABASE_AUTO_CREATE=false`、Secure HttpOnly Cookie，并校验 CSRF 与 Origin。
- 登录和激活由应用与 nginx 双层限流；后端、PostgreSQL、GROBID 均不直接暴露公网。
- LLM/embedding 凭据按 `artifacts/users/<user_id>/llm_settings.json` 独立保存，文件权限为 600；API 只允许当前登录用户管理自己的凭据并只返回掩码。
- 当前生产产品固定 `ACCOUNT_PRODUCT_MODE=personal`，组织表只作为不可见的数据隔离实现；团队/成员管理留给后续单独版本。
- 当前后台任务保持单 worker；不要直接把 Uvicorn 扩为多 worker。项目修订调度需要先升级为外部队列后再横向扩容。
- 首次音频摄入会下载 faster-whisper `base` 模型到 `whisper-cache` 卷。
