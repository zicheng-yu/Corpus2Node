# SESSION — 会话交接摘要

> 下一轮先读本文件，再读 `docs/PROGRESS.md`。PROGRESS 是完整进度真相。

**最近更新**：2026-07-13 · 分支 `feat`

## 本轮完成

1. **缓存与向量正确性**：graph artifact 带完整 provenance 并按输入/模型/prompt/config 自动失效；公开 DTO 不下发 embedding；chat/search/notes/test 与跨图发现都阻止未知或不一致的 embedding 空间。
2. **可溯源质量**：chat 只回实际引用并校验编号与保守词面证据；科学 Claim/Metric 要求 exact quote，bbox 为严格一对一；修复 scientific vendor normalizer 丢 Metric/Insight/DecisionCard。
3. **任务与并发**：长任务事件 artifact 化、可跨重启重放；workflow/chat/report keyed lock 防覆盖并回收空闲锁；科研分析可直接 ingest-only。
4. **安全与部署**：生产强制 token、关闭 docs/内部错误信息、限制模型 endpoint 探测；上传按格式限额并验证 magic/Office 结构；Compose 只暴露 loopback nginx，Vercel 仅显式临时预览。
5. **前端与工程化**：图谱只取一次、共现边默认隐藏；发现报告从首页拆出；访问 token 设置、SSE 错误传播、工作区错误态；补 Vitest、OpenAPI/TS 快照、CI、README、`.env.example`、依赖和 npm 审计。
6. **验收**：194 backend tests、ruff、4 frontend tests、production build、npm audit 0、OpenAPI/TS drift、Compose config、15 个现有 session + 4 份 scientific report 兼容读取均通过。

## 当前状态

- 本轮未调用真实 LLM、未使用远程服务器、未运行 Docker image build；Docker build 已放入 CI，本机 Compose 配置解析通过。
- 用户已有的 `docs/demo/Corpus2Node-演示.pptx` 修改和 `Corpus2Node-客户演示-5页.pptx` 未跟踪文件不属于本轮，必须继续排除；不得 push。
- 三个孤儿 UUID artifact 目录仅从 session 列表忽略，没有删除或移动。

## 下一步最佳动作

用一份真实小语料在浏览器验收 workflow、chat、notes/test、scientific/discovery 的完整交互与 token 成本；之后回到 30 篇 human-gold 双审，或进入 `Course→Corpus` 契约重命名 / 持久化向量库专项。
