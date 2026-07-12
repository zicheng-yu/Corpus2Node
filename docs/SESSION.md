# SESSION — 会话交接摘要

> 下一轮先读本文件，再读 `docs/PROGRESS.md`。PROGRESS 是完整进度真相。

**最近更新**：2026-07-12 · 分支 `feat`

## 本轮完成

1. **科研证据图谱 MVP 已落地**：独立 `scientific/` 垂直包覆盖 Paper/Entity/Relation/Claim/Experiment/Evidence、证据矩阵、跨论文 Insight 与 R&D Decision Card；不改坏通用 GraphArtifact 主线。
2. **证据门**：模型只返回短 evidence alias，后端映射并校验真实 session/source/chunk/locator；无效引用直接过滤。供应商 JSON 方言统一归一化，有限重试；单篇抽取有内容指纹缓存；跨论文模型未过证据门时采用确定性证据综合兜底。
3. **客户页面/API**：新增 `/scientific` 前端页和顶部入口；`POST /scientific/run`、列表/读取/删除 API；报告 artifact 落 `artifacts/scientific/`。
4. **中文策略**：科研说明、结论和建议统一中文；论文、模型、算法、数据集正式英文名称独立保留。通用 graph prompt 同步约束解释字段中文化。
5. **真实验证**：VDN + QMIX + 已配置 DeepSeek 跑通，最终报告 `f1c88905-7d9f-4434-9780-978e94bcd238`：2 papers / 19 entities / 19 relations / 10 claims / 3 experiments / 27 evidence / 2 insights / 1 decision，claim 引用 11/11 有效。
6. **工程验证**：167 passed；ruff clean；前端 production build 通过；本地 `/health` 与 `/api/scientific` 均 200。

## 当前运行状态

- 后端当前以 `uvicorn corpus2node.api.app:app --host 127.0.0.1 --port 8000` 运行；前端 Vite 仍在 5173。
- 如果改用后台 `corpus start`，代码变化后必须重启；普通 restart 无法清理丢失 pidfile 的进程时使用 `corpus force-stop`，但只针对本项目 8000/5173 端口。
- 本轮完成后应有一个 Conventional Commit；未 push。

## 下一步最佳动作

选择约 30 篇同一科研垂直的 gold 论文，接 JATS/TEI/GROBID 与 PDF bbox/table-cell locator；在本轮已跑通的科研契约、证据门、跨论文矩阵和决策卡主线上做正式评估。
