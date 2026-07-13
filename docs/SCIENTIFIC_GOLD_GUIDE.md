# 科研证据 Gold Corpus 标注规范

## 1. 状态与准入

- `unreviewed`：空模板，不能进入指标。
- `silver`：模型预标注，便于人工校正，不能作为正式 gold。
- `ai_verified`：独立盲跑的 AI proxy，经确定性 schema/evidence-id 校验；只允许用于内部可复现性测试，不能称为人工 gold。
- `verified`：至少一名标注者完成全文核对，第二名标注者复核争议项；只有该状态进入正式指标。
- PDF、会议、年份、标题和来源链接必须先与会议录用索引核对。相邻主题论文可保留在候选集，但不得混入 30 篇核心 MARL gold。

## 2. 标注对象

### 实体

使用受控类型：`research_problem`、`method`、`model`、`dataset`、`metric`、`material`、`parameter`、`result`、`limitation`。实体文本采用论文中的正式名称；不要把章节标题、作者或一般背景词标成实体。

### Claim

Claim 是作者可被证据支持或反驳的完整主张。方法介绍、实验观察、理论结论、局限和假设都可成为 Claim，但必须连接到原文 evidence。不要把摘要性改写当成原文 Claim。

### 数值结果

每项记录 `metric`、`value`、`unit`、`condition` 与 evidence。保留论文原始量纲；百分比、小数、均值/方差不可互相猜测。表格数值的 evidence 必须定位到具体 table cell。

### N 元实验关系

实验关系按角色保存，不压缩为孤立二元边：

- `EVALUATED_ON`：必须有 Experiment、Method、Dataset/Environment、Evidence。
- `OUTPERFORMS`：必须有 Experiment、Method、Baseline、Metric、Condition、Evidence；数值缺失时不能补造。
- `SUPPORTS`：必须有 Claim 与 Evidence。
- 其它允许类型：`PROPOSES`、`EXTENDS`、`USES`、`MEASURED_BY`、`REPORTS_RESULT`、`CONTRADICTS`、`REPLICATES`、`LIMITED_BY`、`REQUIRES`、`DERIVED_FROM`、`RELATED_TO`。

## 3. Locator

定位优先级为 `table-cell > sentence > paragraph/page`。记录：

1. `section_path`：从顶层到当前小节；
2. `sentence_id`：JATS/TEI 原 id，或 GROBID sentence id；
3. `page`：PDF 页码从 1 开始；
4. `bboxes`：GROBID `page,x,y,width,height`，多行文本保留多个框；
5. 表格记录 `table_id/table_row/table_column`。

JATS 通常没有 PDF 坐标；不得为了指标填造 page/bbox。只有 JATS 与对应 PDF 完成可靠对齐时才补物理定位。

## 4. 人工复核流程

1. 标注者 A 从 silver 开始阅读全文校正，补齐漏项并删除无直接证据项。
2. 标注者 B 独立复核 Claim、数值、`OUTPERFORMS` 和 locator；记录分歧。
3. 争议项逐条裁决后，填写两名 annotator 并把状态改成 `verified`。
4. 运行 `scripts/evaluate_scientific_gold.py GOLD_DIR PREDICTION_DIR`。工具会跳过非 verified 文件；若一个 verified 都没有则直接报错，避免输出伪正式分数。

AI 内部基准使用独立目录和 `ai_verified` 状态，由 `scripts/run_scientific_benchmark.py` 准入。该结果必须明确标注为 AI blind proxy；即使完成 30 篇，也不能替代上述人工双审流程。

## 5. 正式指标

- 实体：类型化精确率、召回率、F1。
- 关系：关系类型加完整角色集合的精确率、召回率、F1。
- Claim：规范化完整文本精确率、召回率、F1。
- 数值：指标、规范化数值、单位、条件联合精确率、召回率、F1。
- Locator：section/sentence/page/table-cell 严格准确率；bbox 使用同页 IoU `>= 0.8`。

若 reference 只有页级 `Pxxx` 而没有句子或 table-cell，Locator 只能报告“页级 locator 一致率”；由同一 GROBID 文档派生的整页 bbox 集只能报告“bbox 集合复现率”，不得解释为 Claim 句级定位准确率。
