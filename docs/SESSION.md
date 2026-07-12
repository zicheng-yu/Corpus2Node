# SESSION — 会话交接摘要

> 下一轮先读本文件，再读 `docs/PROGRESS.md`。PROGRESS 是完整进度真相。

**最近更新**：2026-07-12 · 分支 `feat`

## 本轮完成

1. **Scientific ingestion**：JATS/TEI/GROBID 统一解析，保留 section/sentence/page/bbox/table-cell/formula/citation；新增解析 API、artifact 存储，并接入普通 workflow 的 best-effort 结构通道。
2. **GROBID 本机服务**：Colima 6 CPU / 12GB；`corpus2node-grobid` 使用官方 `grobid/grobid:0.9.0-crf`，8070 健康；`scripts/grobid.sh` 可 start/stop/status/logs，production compose 也含 grobid。官方 full 镜像无 ARM64 manifest，因此未用 amd64 模拟。
3. **N 元实验关系**：关系类型受控；Claim、Experiment、MetricResult、Condition、Evidence、Method、Dataset、Baseline 显式连接并有角色约束。真实 VDN/QMIX 报告 `ebcce80e-8444-4a99-86fb-1fbcb2ebd026` 含 16 条全 grounded N 元关系。
4. **MARL corpus**：桌面 `/Users/zicheng/Desktop/marl-top3-2024-2025`；六届官方索引 21,224 条，高召回候选 131 篇（101 core / 30 adjacent review），PDF 131/131；最终 30 篇每个会议年度 5 篇。
5. **真实 30 篇流程**：DeepSeek silver 30/30，GROBID TEI/ScientificDocument 30/30；431 entities / 376 relations / 166 中文 Claims / 74 numeric results / 143 locators（141 bbox、5 table-cell）。所有 evidence locator 完整，错误清单为空。
6. **正式评测**：新增 entity/relation/Claim/numeric PRF、locator strict accuracy、bbox IoU，且 verified-only。30 篇目前是 silver；`metadata/formal-eval-status.json` 明确 verified=0，领域人工双审前拒绝输出伪正式分数。
7. **工程验证**：173 passed；ruff clean；真实 DeepSeek、真实 GROBID、真实 PDF 均跑通。

## 当前运行状态

- GROBID：`scripts/grobid.sh status`，容器 `corpus2node-grobid`，`http://127.0.0.1:8070`。
- Colima 当前为 6 CPU / 12GB；停止 GROBID 用 `scripts/grobid.sh stop`，停止虚拟机用 `colima stop`（本轮保持运行供项目使用）。
- 桌面 corpus 权威目录：`pdfs/all-candidates`、`pdfs/selected-corpus-30`、`gold/selected-corpus-30-annotations`、`grobid/{tei,documents}`。
- 本轮代码应独立 Conventional Commit；不要 stage/commit `docs/demo` 中用户的 PPTX 修改；未 push。

## 下一步最佳动作

由领域标注者按 `docs/SCIENTIFIC_GOLD_GUIDE.md` 双审 30 篇 silver，裁决后改为 `verified`，再运行 `scripts/evaluate_scientific_gold.py` 记录正式 baseline。其余工程主线已经完成。
