# 科研证据图谱与 R&D 决策 AI 演进方案

## 结论

Corpus2Node 面向 R&D 和企业知识库时，不应只强调“把论文做成知识图谱”，而应升级为：

> **从原始科技文献中抽取可核查的科研实体、关系、主张、实验与证据，构建科研证据图谱，并进一步发现矛盾、空白、技术路线和下一步实验机会。**

核心差异不是论文摘要，而是：

1. 从 PDF、JATS/XML 等原始文献保留章节、页码、公式、表格、图和引用定位。
2. 把“方法、材料、数据集、指标、结果、限制”等科研对象抽成类型化节点与关系。
3. 把每个结论建模为 `claim -> evidence -> experiment -> source locator` 证据链。
4. 跨论文对齐同一实体、实验条件与指标后，再做比较、矛盾和研究空白发现。
5. 最终输出带证据等级、反方证据和不确定性的研发决策卡，而不是无依据建议。

## 当前实现状态（2026-07-12）

技术主线 MVP 已完成，不再只是方案：

- `scientific/` 已有独立 Paper / Entity / Relation / Claim / Experiment / Evidence / Insight / Decision 契约。
- 论文原文块先以短 evidence alias 进入模型，返回后由后端严格映射到真实 `session_id / source_id / chunk_id / locator`；编造的引用会被剔除。
- 已实现论文证据矩阵、跨论文洞察和研发决策卡；供应商 JSON 字段差异有统一归一化，失败有有限重试，单篇抽取按内容指纹缓存。
- 模型综合未通过证据校验时，使用明确的确定性证据综合兜底，绝不把不可核查的模型输出展示成科研事实。
- 前端 `/scientific` 支持多选文献、研发目标、历史报告、证据矩阵、洞察、决策卡和原文定位。
- VDN/QMIX + DeepSeek 已真实跑通：报告 `f1c88905-7d9f-4434-9780-978e94bcd238` 含 2 篇论文、19 个实体、19 条关系、10 条主张、3 个实验、27 条证据、2 条洞察和 1 张决策卡；主张引用有效率 11/11。

当前仍属于基于现有 PDF chunk 的 Phase 0.5。下一步 Phase 1 的核心不是重写这条主线，而是把 locator 从“文件名 + 段落”升级为 JATS/TEI/GROBID 的 section/page/bbox/table cell，并以约 30 篇 gold corpus 做实体、关系、claim、数值和 locator 评估。

## 1. 为什么需要单独的科研垂直能力

通用文档图谱通常只有“概念 + 关系 + chunk 引用”，不足以支持研发决策：

- 同一个术语可能指材料、方法、任务或指标，需要类型和领域本体。
- 论文的关键关系经常跨句、跨章节，甚至跨正文、表格和附录。
- “A 优于 B”只有在数据集、指标、实验条件、统计口径一致时才可比较。
- 一篇论文的背景描述、作者主张、实验事实、引用他人结论不能混成同等级事实。
- 研发决策需要看到反例、限制、复现实验、时间版本和证据强弱。

因此科研版应是客户配置体系中的第一个垂直能力包，而不是 fork：

```text
product core
  -> scientific profile
     -> scientific parsers
     -> scientific ontology pack
     -> evidence graph
     -> R&D decision workflows
```

## 2. 科研证据图谱的数据模型

### 2.1 文献与身份层

- `Paper`：标题、摘要、DOI、年份、venue、开放获取状态。
- `PaperVersion`：preprint、accepted manuscript、version of record、内部报告版本。
- `Author`、`Institution`、`Venue`、`Funder`、`Project`。
- `Citation`：引用方向、正文引用位置、引用语境和引用意图。

外部元数据可通过 Crossref、OpenAlex 或 Semantic Scholar 对齐 DOI、作者、机构、主题和引用网络。OpenAlex 的实体覆盖 works、authors、institutions、topics、funders 等；Semantic Scholar 还提供引用、参考文献和 SPECTER2 表征。

### 2.2 科研实体层

首版通用科研本体建议限定为：

| 类型 | 例子 |
|---|---|
| ResearchProblem / Task | 蛋白质结构预测、低资源语音识别 |
| Method / Model / Algorithm | Transformer、有限元法、催化合成路线 |
| Material / Substance / Component | 催化剂、合金、药物分子、器件模块 |
| Dataset / Sample / Population | ImageNet、患者队列、实验样品 |
| Metric / Property | F1、屈服强度、转化率、毒性 |
| Instrument / Software | 显微镜、仿真软件、测量装置 |
| Parameter / Condition | 温度、压力、学习率、剂量 |
| Result / Observation | 数值结果、趋势、失败现象 |
| Limitation / Risk | 数据偏差、适用范围、工艺风险 |
| Hypothesis / Claim | 论文提出或验证的科研主张 |

领域客户通过 ontology pack 扩展类型和词表，例如制药加入 Gene / Protein / Disease / Drug，材料加入 CrystalStructure / Process / MechanicalProperty；核心代码不硬编码具体行业。

### 2.3 关系层

首版关系应比当前通用 `relates_to` 更明确：

- `ADDRESSES`：方法解决问题。
- `PROPOSES` / `EXTENDS` / `USES`：提出、改进、使用方法或组件。
- `EVALUATED_ON` / `MEASURED_BY`：在数据集或样品上用指标测量。
- `HAS_PARAMETER` / `UNDER_CONDITION`：实验参数与条件。
- `REPORTS_RESULT`：实验报告数值或观察。
- `OUTPERFORMS`：在明确条件与指标下优于基线。
- `SUPPORTS` / `CONTRADICTS` / `REPLICATES`：证据支持、冲突或复现主张。
- `LIMITED_BY` / `REQUIRES`：限制与前置条件。
- `CITES` / `DERIVED_FROM` / `SAME_AS`：引用、来源与实体对齐。

`OUTPERFORMS` 不能只是一条二元边，应连接一个实验上下文，至少包含 dataset/sample、metric、value、baseline、condition 和 evidence span。

### 2.4 主张与证据层

建议新增独立 `ScientificClaim`，不要把所有句子直接提升为 Concept：

```text
ScientificClaim
  claim_type: finding | comparison | causal | limitation | hypothesis
  polarity: positive | negative | mixed
  modality: observed | suggested | uncertain
  subject / predicate / object
  scope / population / condition
  evidence_ids[]
  source_paper_id
```

`EvidenceSpan` 至少保存：

```text
paper_id
source_id
section_path
page
bbox
sentence_text
table_or_figure_id
row / column / cell
citation_marker
```

任何跨论文结论必须能逐层回到 claim、实验、原句或表格单元格和原 PDF 位置。

## 3. 从原始科技文献构图的流水线

### 阶段 A：身份识别与去重

1. 从文件、标题页和参考文献识别 DOI、arXiv ID、PMID 等标识。
2. 用 Crossref / OpenAlex / Semantic Scholar 补齐文献元数据和引用网络。
3. 合并 preprint、会议版、期刊版和重复 PDF，但保留 `PaperVersion`。

### 阶段 B：结构化解析

优先级：

1. 有 JATS/XML、TEI 或 publisher XML 时直接解析结构化全文。
2. 只有 PDF 时使用 GROBID 类科学文献解析器输出 TEI，并保留 title、author、section、paragraph、sentence、reference、figure、table、formula 的 PDF 坐标。
3. OCR/视觉路径只作为扫描件和复杂版面的补充。

JATS 是描述期刊文章文本、图形内容和元数据的标准；GROBID 面向技术/科学 PDF，可输出结构化 TEI 和原 PDF 坐标，因此比把 PDF 直接切成纯文本更适合证据定位。

### 阶段 C：论文结构与修辞角色识别

把文本划分为 Background / Objective / Method / Result / Discussion / Limitation / Conclusion，并区分：

- 作者自己的贡献；
- 对前人工作的转述；
- 实验事实；
- 推测、未来工作和限制。

这一步决定后续 claim 的证据等级，不能只依赖章节标题。

### 阶段 D：文档级科研信息抽取

不要继续用“每个 chunk 独立抽概念再 merge”的单一模式。科研版需要：

1. section 内实体和关系抽取；
2. 全文 coreference / abbreviation resolution；
3. 跨章节 salience 判断；
4. document-level N-ary relation，将 method、dataset、metric、result、condition 绑定到同一实验；
5. 表格和正文结果对齐。

SciERC 展示了科学实体、关系和共指的联合抽取；SciREX 进一步说明关键科研关系经常是文档级多元关系；SciER 的 full-text 数据也表明只处理摘要会丢失大量上下文实体和关系。

### 阶段 E：规范化与实体链接

- 缩写展开、别名、化学式、单位和符号规范化。
- 方法、数据集、材料、疾病等链接到客户领域本体或公共 ID。
- 数值、单位、置信区间和显著性使用确定性解析，不交给 LLM 自由改写。
- paper embedding 与 chunk embedding 分开；论文相似性可引入利用引用图训练的科学文献表征，不能只用通用文本 embedding。

### 阶段 F：质量门

每个 artifact 记录：

- parser 版本、模型版本、prompt 版本、本体版本；
- 自动抽取置信度；
- 原始 evidence locator；
- 人工确认/驳回状态；
- 更新、撤回或被新版本取代状态。

确定性检查至少包括：

- DOI 和引用方向一致性；
- 关系端点类型合法；
- `OUTPERFORMS` 的指标、值、基线和条件齐全；
- 数值是否能在原句或表格单元格逐字找到；
- claim 是否有 evidence；
- 同一结论是否混用了不同数据集、单位或实验条件。

## 4. 面向 R&D 的知识发现

科研知识发现不能只用 embedding 相似度寻找“有关联的概念”，建议形成六类可解释任务：

### 4.1 证据矩阵

对同一问题按 `method x dataset/sample x metric x condition x result` 对齐论文，生成可筛选的比较矩阵。不可比较的实验明确标记原因，不强制排名。

### 4.2 矛盾与边界条件

发现 subject / predicate 接近但 polarity 或结果方向相反的 claims，再比较实验条件、样本、版本和证据强度，区分真正矛盾与条件不同。

### 4.3 技术路线与谱系

结合 `EXTENDS`、`USES`、citation 和时间，展示方法从哪篇工作演化而来、解决了什么限制、又引入了什么新限制。

### 4.4 研究空白

研究空白不是简单的“图上缺一条边”，而是：

- 高价值问题缺少可靠方法或独立验证；
- 方法只在单一数据集/材料/条件验证；
- 关键指标未报告或不可比较；
- 相邻领域已有成熟方法，但目标领域尚未验证；
- 大量主张依赖同一个源头，缺少独立研究组复现。

### 4.5 方法迁移机会

从两个领域寻找共享约束、输入输出结构或评价目标，生成“为什么可能迁移、需要满足什么条件、最小验证实验是什么”的提案，而不只给概念相似度。

### 4.6 研发决策卡

每张卡固定输出：

- 决策问题；
- 当前证据支持的结论；
- 关键证据与反方证据；
- 证据等级和不确定性；
- 不可比较或缺失的信息；
- 推荐的最小下一步实验；
- 若结论错误的主要风险；
- 可点击的 claim / table cell / PDF locator。

## 5. 产品呈现应该突出什么

首页定位建议从“资料变知识图谱”升级为双层表达：

> **把原始科技文献变成可核查的科研证据图谱。**
>
> 自动识别方法、材料、实验、指标、结果与限制，跨论文发现矛盾、研究空白和技术迁移机会，为 R&D 决策提供可回溯证据。

演示主线应是：

```text
原始 PDF / XML
  -> 结构、表格、公式、引用定位
  -> 科研实体与实验关系
  -> claim-evidence graph
  -> 跨论文证据矩阵 / 矛盾 / 空白
  -> R&D 决策卡
  -> 点击回到原 PDF 句子或表格
```

不要把“论文问答”当压轴；压轴应是“系统发现两篇论文结论冲突，指出差异来自实验条件，并建议一个最小验证实验”。

## 6. 在当前仓库中的落点

建议新增垂直包而不是改坏通用主线：

```text
src/corpus2node/scientific/
  schemas.py       # Paper / Claim / Experiment / EvidenceSpan / typed relations
  metadata.py      # DOI / OpenAlex / Crossref / S2 metadata adapters
  parse.py         # JATS / TEI / GROBID normalization
  ontology.py      # base scientific ontology + customer ontology pack
  extract.py       # section + document-level extraction
  normalize.py     # entity linking / unit / abbreviation / version merge
  build.py         # ScientificEvidenceGraph
  critic.py        # claim/numeric/comparability quality gates
  discovery.py     # matrix / contradiction / gap / transfer
  decisions.py     # R&D decision cards
```

与现有能力的复用关系：

- 复用 `ingest/adapters` 注册机制，但增加 JATS / TEI / GROBID adapter。
- 复用 artifact-first、LangGraph workflow、LLM purpose、SSE job 与引用展示。
- 复用 networkx/检索基础设施，但科学实体合并、数值比较和证据等级使用独立确定性逻辑。
- chat agent 增加 `search_claims`、`compare_experiments`、`trace_citation`、`find_counterevidence` 工具。
- 通用 `GraphArtifact` 暂不强塞全部科研字段；首版新建 `ScientificGraphArtifact`，验证稳定后再抽共享基类。

## 7. 分阶段实施

### Phase 1：Scientific ingestion MVP

- 选择一个垂直领域和约 30 篇论文作为 gold corpus。
- 接 JATS/TEI + GROBID PDF 结构解析，保留页码和 bbox。
- 实现 Paper、ScientificEntity、ScientificClaim、EvidenceSpan、Experiment 五类核心契约。
- 抽取 Problem / Method / Dataset-or-Sample / Metric / Result / Limitation。
- 前端支持点击 claim 回到 PDF 原句。

验收：文献身份去重正确；主要章节、引用和表格可定位；claim 引用覆盖率达到可人工验收水平。

### Phase 2：跨论文证据图谱

- 实体链接、缩写和版本合并。
- 文档级多元实验关系与表格数值抽取。
- citation graph、method lineage 和证据矩阵。
- 建立领域专家标注的 entity / relation / claim / numeric gold set。

### Phase 3：知识发现与 R&D 决策

- 矛盾检测、边界条件解释、研究空白和方法迁移。
- 研发决策卡、证据等级、反方证据和最小实验建议。
- 对发现结果加入专家 keep / reject / edit，反馈进入评估集，不直接训练黑箱偏好。

### Phase 4：企业化

- 客户 ontology pack、内部报告/实验记录/专利 adapter。
- 权限、审计、人工审批和敏感项目隔离。
- 增量文献监测：新论文进入后只更新受影响的 claims、比较矩阵和决策卡。
- 研发项目、内部实验、外部论文统一进证据图，但严格标记来源等级与访问权限。

## 8. 评估指标

| 层级 | 关键指标 |
|---|---|
| 解析 | section / reference / table / formula 定位准确率；PDF bbox 可点击率 |
| 实体 | typed entity precision / recall / F1；缩写和 entity linking accuracy |
| 关系 | relation F1；document-level N-ary relation exact/partial match |
| 主张 | claim span F1；claim type / polarity / modality accuracy |
| 数值 | value-unit-condition exact match；表格单元格回溯率 |
| 证据 | claim evidence coverage；错误引用率；locator 可达率 |
| 发现 | 矛盾/空白/迁移建议的专家 precision、novelty、actionability |
| 决策 | 找证据耗时降低、关键反方证据召回率、决策卡专家采纳率 |

最重要的上线门槛不是“图有多少节点”，而是：关键结论能否回到原始证据、跨论文比较是否条件一致、系统是否主动展示反方证据和不确定性。

## 参考基础设施与研究

- [GROBID documentation](https://grobid.readthedocs.io/en/latest/)：科学 PDF 到 TEI、结构与坐标。
- [NISO JATS 1.4](https://www.niso.org/standards-committees/jats)：期刊文章全文与元数据 XML 标准。
- [Crossref REST API](https://www.crossref.org/documentation/retrieve-metadata/rest-api/)：DOI 与出版元数据。
- [OpenAlex API](https://developers.openalex.org/api-reference/introduction)：works、authors、institutions、topics、funders 和引文网络。
- [Semantic Scholar API](https://www.semanticscholar.org/product/api)：论文、作者、引用、参考文献和 SPECTER2。
- [ORKG system walkthrough](https://arxiv.org/abs/2206.01439)：机器可操作的科研贡献表示与比较。
- [SciERC](https://aclanthology.org/D18-1360/)：科研实体、关系和共指联合抽取。
- [SciREX](https://aclanthology.org/2020.acl-main.670/)：文档级科研实体与多元关系。
- [SciER](https://aclanthology.org/2024.emnlp-main.726/)：full-text 科研实体与关系数据集。
- [SciRepEval / SPECTER2](https://aclanthology.org/2023.emnlp-main.338/)：科学文献表征与多任务评估。
