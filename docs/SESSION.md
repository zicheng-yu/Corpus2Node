# SESSION — 会话交接摘要

> 下一轮先读本文件，再读 `docs/PROGRESS.md`。PROGRESS 是完整进度真相。

**最近更新**：2026-07-13 · 分支 `feat`

## 本轮完成

1. **冻结 prediction**：桌面 MARL corpus 的 30 篇 DeepSeek silver 已复制为 immutable snapshot，manifest 记录逐文件 SHA-256 与 bytes。
2. **AI blind proxy 标注**：不读取 prediction，从 PDF 独立盲标 30/30；确定性裁决删除缺少 evidence/N 元必需角色的关系。Reference 共 413 entities / 260 relations / 154 Claims / 61 numeric / 120 locators。
3. **状态分轨**：独立审计指出 AI 结果不能占用人工双审 `verified`，因此新增 `ai_verified`；默认正式 evaluator 仍只准入人工 `verified`，内部 benchmark 显式准入 AI proxy。
4. **真实评测**：Entity exact F1 0.3863；full-role Relation exact F1 0.0283；heuristic Claim fuzzy F1 0.4375；Claim exact/Numeric exact F1 0；page/table locator key agreement 0.9250、GROBID-derived bbox-set agreement 0.9237。
5. **审计结论 WARN**：未发现 prediction 直接泄漏，当前结果可重算；但 reference 复用 prompt/schema/page-selection，属于相关 AI proxy，不是 human gold。120 locators 中 115 个仅页级，locator 分数不能解释为句级定位准确率。
6. **审计链增强**：prediction/reference manifest 校验文件集合、bytes、SHA-256；reference 另存并校验完整 prompt artifact 与 30 个源 PDF hash；结果记录两个 manifest digest、prompt digest、指标口径、locator 粒度与 bootstrap 限制。说明见 `docs/SCIENTIFIC_BENCHMARK.md`。

## 当前运行状态

- GROBID：`scripts/grobid.sh status`，容器 `corpus2node-grobid`，`http://127.0.0.1:8070` 健康。
- 桌面 corpus：`/Users/zicheng/Desktop/marl-top3-2024-2025`；内部结果和审计在 `results/`。
- 用户的 `docs/demo/*.pptx` 改动不属于本轮，提交时必须排除；不得 push。

## 下一步最佳动作

由 MARL 领域专家按 `docs/SCIENTIFIC_GOLD_GUIDE.md` 双审并裁决 30 篇，生成真正的 `verified` human gold。技术侧优先把 Claim/数值 evidence 从页级升级为原文 quote + sentence/table-cell locator，并稳定实体 canonical ID 与 N 元角色 ID，之后再重跑 human-gold baseline。
