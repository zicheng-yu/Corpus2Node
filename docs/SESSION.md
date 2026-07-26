# SESSION — 会话交接摘要

> 下一轮先读本文件，再读 `docs/PROGRESS.md`。PROGRESS 是完整进度真相。

**最近更新**：2026-07-27

## 本轮完成

1. **测试服务器已上线**：`https://corpus2node.digitmasterai.com` -> 宿主 nginx/TLS -> `127.0.0.1:8080` -> Compose frontend/backend/PostgreSQL；公网 health、HTTPS、未授权 401、8080 私有绑定和重启恢复均验证。
2. **生产构建适配**：新增国内网络 Compose 覆盖与 registry/Debian/PyPI artifact 镜像参数；生产启动直接运行 venv 中的 Alembic/Uvicorn，不再因 `uv run` 联网而 502。
3. **数据已复制并核对**：116 个 artifact、122473324 bytes、SHA-256 `e73aa1e...9284c`，包括 15 sessions/graphs；本机与服务器 dry-run 完全一致，未移动或改写原文件。
4. **迁移兼容**：历史 source 的本机绝对路径读取时自动重定位到当前 `session/uploads`；inventory 排除 macOS 元数据。相关账号/会话/迁移测试 24 passed。
5. **管理员、正式迁移与模型**：`yuzichengyzc@gmail.com` 已激活为 platform_admin；同时拥有 Platform 与 Imported Workspace 两个 Team Beta 组织。正式登记 3 projects / 62 resources，幂等复跑新增 0，62/62 路径存在；迁移后 PostgreSQL dump 已生成。共享注册表的 DeepSeek/Kimi 密钥已迁移，权限 600，两个供应商 `/models` 均探测成功。
6. **普通用户信息架构**：顶部只剩项目/新建与搜索/设置；设置已恢复为非全屏 modal，账号、角色、工作区、团队和个人偏好在弹窗内按权限显示，platform_admin 额外看到原有模型 API 与平台管理。TopBar 已删除科研证据、`Imported Workspace`、用户名和成员角色；Team/Platform 区段 lazy load。
7. **member 演示账号**：`yuzichengyzc+demo@gmail.com` 已生成 Imported Workspace 的 member 邀请，待用户打开一次性链接设置密码；该账号不具备平台、模型、套餐或成员管理权限。
8. **项目首页回退**：账号模式 `/` 已恢复原 `HomePage`，保留知识库/资料集分组、搜索、筛选和拖拽；新团队项目卡片页暂不作为入口，团队 Project/自动修订后端仍保留。
9. **知识发现中心整合并上线**：新增 `/discover`，统一“跨资料发现 / 科研证据分析”的资料选择、目标输入和跨类型历史时间线，两类 SSE/schema/artifact 保持独立；首页只负责携带所选 session 进入，`/scientific` 保留重定向。
10. **资料删除与设置体验修复并上线**：线上删除失败是 member 被旧 admin 权限拦截（403）；现 member 可软归档团队资料、viewer 仍只读，artifact 不物理删除。设置恢复为 modal，平台管理员仍可配置 provider / `base_url` / `api_key` / model / purpose。后端 208 passed、前端 12 tests、ruff/build 通过；线上 release `settings-modal-delete-20260715-1945` 健康。
11. **个人账号 + BYOK 已上线**：生产固定 `ACCOUNT_PRODUCT_MODE=personal`；每个账号拥有不可切换的隐藏个人资料库和 `artifacts/users/<user_id>/llm_settings.json` 600 凭据文件。设置只剩账号、模型与 API、外观、个人偏好；所有账号可配置自己的 API，团队/成员/平台/团队项目页均不打包。后端 210 passed、前端 12 tests、Alembic `20260715_0002`，线上 release `personal-byok-20260715-2010` 健康。
12. **BYOK 新模型流程修复并上线**：账号模式的新凭据先手填模型并保存，已保存凭据再以 `credential_id` 读取模型列表和切换默认模型，生产不再触发任意 endpoint 探测 403。管理员个人注册表已新增并验证 `deepseek-v4-flash`，DeepSeek `/models` 同时返回 flash/pro；前端 13 tests + production build 通过。
13. **力导向共现边回撤**：撤销 7 月 13 日“默认隐藏共现边”的前端改动，删除显示/隐藏按钮和状态；`CO_OCCURS_WITH` 恢复为默认显示并参与布局。新增回归测试防止再次被过滤，前端现为 14 tests + production build 通过。
14. **零起步 BYOK 模型枚举恢复**：移除生产环境“只能探测已保存凭据”的 403；已登录用户可先填写公网 HTTPS endpoint/API Key 读取模型，再选择模型并保存。登录、HTTPS、loopback/内网拒绝和密钥不回显仍保留；后端 211 passed、前端 14 tests、ruff/build 通过。

## 当前状态

- 管理员账号个人资料库为 Imported Workspace，保留原 15 个 session、3 个项目和历史 artifact；个人模型文件现有 3 credentials / 6 bindings。新增 DeepSeek V4 Flash 后，用户已在浏览器成功绑定 graph/chat/critic/exam；Kimi 继续保留 vision/embedding 的原绑定。
- demo 账号已从共享 member 视角切为独立 Free 个人资料库 `member 的资料库`，不会再看到管理员资料；首次打开“模型与 API”会创建自己的空 600 凭据文件。
- 当前 Compose 使用 deterministic hashing embedding；Kimi `kimi-k2.6` 不是 embedding API。要启用语义 embedding，需另配真正的 OpenAI-compatible embedding 模型后切 `EMBED_PROVIDER=openai_compatible`。
- GROBID 镜像在服务器使用的国内代理返回 403，因此默认 profile 未启动；PDF 仍可走 Kimi Files API，精细 TEI/bbox 路径暂不可用。
- 线上 `/discover`、设置兼容链接与 health 已验证；数据库为 2 users / 63 resources / 3 organizations（其中组织只是个人隔离实现）。删除失败的目标 session 后续已成功归档，并生成一个 ready 项目修订。
- 团队/项目自动修订后端保留在 `teams` 模式，但当前生产和 UI 不启用；后续客户协作应作为单独产品版本设计。
- 代码与交接文档已按功能整理为本地提交，未 push。工作树仅保留未被应用入口引用的 `frontend/src/pages/SettingsPage.tsx` 与 `SettingsPage.test.tsx` 两份未跟踪中间文件，等待用户确认是否删除。

## 下一步最佳动作

用管理员账号刷新后确认历史资料和“模型与 API”的 3 个凭据仍可用；再用 demo 账号确认首页为空、独立添加一个 API、上传资料并跑通“建图 -> 知识发现”。新账号通过 `corpus2node-admin invite-user --email ... --name ...` 生成激活链接；团队客户版不在当前验收范围。
