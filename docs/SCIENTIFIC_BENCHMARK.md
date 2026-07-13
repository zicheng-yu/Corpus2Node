# 科研证据抽取内部基准

## 基准性质

本基准覆盖 30 篇 ICLR、ICML、NeurIPS 2024-2025 MARL 论文。待测输入是冻结的 DeepSeek silver snapshot；reference 是另一轮不读取 prediction 的 AI blind pass，并经确定性 schema、evidence ID 和 N 元角色约束裁决。

Reference 状态为 `ai_verified`，表示“AI proxy 已通过程序校验”，不表示人工验证。人工双审 gold 仍使用 `verified`，流程见 `docs/SCIENTIFIC_GOLD_GUIDE.md`。

## 2026-07-13 基线

| 指标 | Precision | Recall | F1 | 口径 |
|---|---:|---:|---:|---|
| Entity | 0.3782 | 0.3947 | 0.3863 | 类型 + 规范化字符串 exact |
| Relation | 0.0240 | 0.0346 | 0.0283 | 类型 + 完整 N 元角色集合 exact |
| Claim fuzzy | 0.4217 | 0.4545 | 0.4375 | 共享页/table evidence，字符相似度阈值 0.45 |
| Claim exact | 0.0000 | 0.0000 | 0.0000 | 规范化完整中文文本 exact |
| Numeric | 0.0000 | 0.0000 | 0.0000 | metric/value/unit/condition 四字段 exact |

Reference 共 413 entities、260 relations、154 Claims、61 numeric results、120 locators。Locator key agreement 为 0.9250，GROBID-derived bbox-set agreement 为 0.9237；其中 115 个是 page-only、1 个有 sentence ID、4 个是 table-cell，因此这两个数不能解释为 Claim 句级定位准确率。

## 结果解释

- 结果说明当前抽取可重复识别一部分核心实体和语义 Claim，但自由文本 Claim 无 exact 重合。
- Relation type 往往可重复，但完整实验角色文本难以 exact 对齐；严格 Relation F1 很低。
- Numeric 的 metric/condition 表述不稳定，四字段 exact F1 为 0；这不等于系统完全无法抽数值。
- 当前最重要的改进点是稳定实体 canonicalization、把实验角色连接到实体 ID、为 Claim/数值保存原文 quote 与 sentence/table-cell locator。

## 复现

```bash
uv run python scripts/run_scientific_benchmark.py
```

脚本会验证 prediction/reference manifest 的文件集合、字节数和 SHA-256，并校验 reference 固化的 prompt 原文及 30 个源 PDF hash；要求 30 篇 `ai_verified` reference，并写出 micro、论文级 macro bootstrap、逐论文结果和指标口径。完整数据、结果与 `EXPERIMENT_AUDIT.*` 位于：

```text
/Users/zicheng/Desktop/marl-top3-2024-2025
```

该路径是本机实验产物位置，不是仓库内可移植 fixture。对外报告必须使用“AI blind proxy 内部一致性基准”，不得称为 human gold accuracy。
