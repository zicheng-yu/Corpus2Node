# SESSION — 会话交接摘要

> 下一轮先读本文件，再读 `docs/PROGRESS.md`。PROGRESS 是完整进度真相。

**最近更新**：2026-07-14

## 本轮完成

1. **账号与租户**：async SQLAlchemy + PostgreSQL/SQLite + Alembic；邀请激活、Argon2、opaque Cookie session、CSRF/Origin、角色矩阵、平台管理员 CLI/后台。
2. **全链路隔离**：账号模式下 artifact 必须在 `resources` 登记；sessions/graph/search/workflow/chat/notes/test/discovery/scientific/export/SSE 均按组织授权，跨租户返回 404；个人产物按组织+用户隔离。
3. **团队项目与修订**：稳定 Project、60 秒合并窗口、项目级串行/dirty-rerun、指纹幂等、公共图谱确定性重建、scientific 最多 100 篇 map-reduce、失败保留稳定版本、停用来源生成新修订。
4. **套餐、分享与用量**：Free/Team Beta、组织覆盖和只读降级；LLM/生成任务用量幂等记录；外链在创建时固化独立 JSON 白名单快照，256-bit token 仅存 hash，后续源报告变化不影响快照。
5. **前端与部署**：登录/激活、组织切换、项目协作、团队设置、平台管理（含试用/额度覆盖/全局用量）、修订历史和分享页；Compose 加 PostgreSQL，启动前迁移，nginx 登录/激活限流；artifact 导入支持 dry-run/hash 核对且不移动文件。
6. **验收**：ruff clean；204 backend tests；4 frontend tests；OpenAPI/TS 契约重新生成；TypeScript + Vite production build、Alembic 初始迁移和 Compose 配置解析通过。

## 当前状态

- 本轮没有调用真实 LLM、没有使用远程服务器、没有启动 Docker 镜像，也没有 push。
- 生产第一验收门仍需在实际 HTTPS + PostgreSQL 环境手工走通；自动测试已覆盖邀请一次性/过期、Argon2、CSRF、注销、角色/跨租户、私有产物、配额、修订幂等与失败保稳、分享撤销和迁移非破坏性。
- 首版按计划不含邮件、支付、MFA/SSO、对象存储和多 worker；邀请链接由平台后台复制发送，Team Beta 手动分配。
- `AGENTS.md` / `CLAUDE.md` 为本地忽略的操作手册；已在当前工作区同步生产账号模式的架构约定，提交中的权威更新在 `docs/CUSTOMIZATION.md`、`docs/PROGRESS.md` 和本文件。

## 下一步最佳动作

准备一个 HTTPS staging，按部署文档先备份 artifact、建 PostgreSQL、bootstrap 管理员并 dry-run 导入；创建首个客户组织后，让负责人和第二成员分别上传论文，人工验收公共修订与只读分享快照。
