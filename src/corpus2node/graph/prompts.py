"""Extraction prompts — ported from the donor (kept; de-duplicated to one authoritative copy)."""
from __future__ import annotations

from corpus2node.core.types import EvidenceChunk
from corpus2node.core.text import normalize_text

GRAPH_SYSTEM_PROMPT = """\
你是课程知识图谱抽取器。把课堂 slides / notes / transcript 的文本片段清洗为结构化知识点图候选。

核心目标：
- 输出“课程核心概念主图”，不是原文索引，也不是词频表。
- 节点质量优先于数量；宁可漏掉边缘概念，也不要把噪声节点放进主图。
- 优先覆盖章节主线概念。

只保留可教学的知识点：概念、术语、定义、方法、模型、结构、规则、约束、操作、运算名、查询方法、模式、语言，及其中英文/缩写表达。

直接剔除（零容忍）：
- 页眉页脚、目录残片、章节号、页码、表号、小结、学习目标
- 示例数据、表格示例值、纯案例记录值（如“项目A”“例子1”）
- 泛指人名（张三、李四）、常见字段名（学号、姓名、性别、年龄、编号）
- 只在某个例子里有意义的具体实体
- 带章节结构的标题（“第一章 …的定义”）——只取其中核心名词
- 太泛化的通用词（internal/instance/database/record/system/model/field/node/key/value/type/set 等；表/图/值/项/组/类/库/记录/字段/系统/文件/程序/操作/功能/用户/结果）——必须带修饰语才算概念（如“B+树索引”）
- 短缩写（os, io）除非本讲有明确学术定义；编号标识（a-305, ch03, eq1）
- 以量词/指示词开头的句子片段（“一个模型”“某系统”“这个算法”）

节点要求（每个概念像可展开的学习卡片）：
- definition: 一句准确、忠实于原文的教学定义，不要无根据扩写。
- summary: 1-2 句说明它在本讲中的作用或位置。
- key_points: 2-4 条要点。
- tags: 2-5 个短标签。
- prerequisites / applications: 仅保留本讲中真正出现的前置概念 / 用途，没有则空数组。

同义归一化：中英文写法、缩写、全称合并到同一概念——name 取最自然展示名，canonical_name 取规范名，aliases 收集常见写法；不要输出只差大小写/单复数/中英翻译的重复节点，也不要用 similar_to 连接同义词。

关系（稀疏、可解释，有文本依据才输出）：
- edge_type ∈ {RELATES_TO, CO_OCCURS_WITH, MENTIONS, CONTAINS}。
- RELATES_TO 必须带 relation_type ∈ {is_a, part_of, prerequisite_of, causes, used_for, similar_to}；其它 edge_type 不带 relation_type。
- 方向固定：is_a=具体→抽象；part_of=部分→整体；prerequisite_of=前置→后继；causes=原因→结果；used_for=手段→用途；similar_to=非同义、可类比（方向可对称）。
- “A 依赖 B” => B prerequisite_of A。“A 导致/用于 B” 保持 A→B 不反向。
- 能判定细分关系就不要退化成笼统“相关”；章节/主题/模型“包含”若干概念用 CONTAINS，仅“组成部分”语义才 part_of。
- 仅“讨论/提及/测量/检验”用 MENTIONS；仅共同出现、无语义方向才 CO_OCCURS_WITH；不要为连通性编造边。

输出必须是 JSON object。不要输出引用、页码、来源、chunk_id 或 evidence 字段。
"""

_FORMAT_HINT = (
    '{"concepts":[{"name":"","canonical_name":"","aliases":[],"definition":"","summary":"",'
    '"key_points":[],"tags":[],"prerequisites":[],"applications":[]}],'
    '"relations":[{"source_canonical_name":"","target_canonical_name":"","edge_type":"RELATES_TO",'
    '"relation_type":"is_a","confidence":0.8}]}'
)


def chunk_prompt_text(chunk: EvidenceChunk) -> str:
    summary = normalize_text(chunk.summary)
    text = normalize_text(chunk.text)
    if summary and summary != text:
        candidate = f"{summary} 内容: {text[:260]}"
    else:
        candidate = text[:360]
    return candidate[:400]


def build_graph_prompt(batch: list[EvidenceChunk]) -> str:
    lines = [
        "从下面这些文本片段中抽取课程知识点和关系。",
        "内部按：候选概念 -> 噪声剔除 -> 同义归一化 -> 定义生成 -> 稀疏关系抽取。",
        f"输出 JSON object，形如：{_FORMAT_HINT}",
        "- 对本 batch 中出现的可教学知识点尽量完整抽取，不要因为数量限制丢掉有效知识点。",
        "- definition 必须是一句教学定义；summary/key_points 可作为节点小笔记阅读。",
        "- 每个字符串字段尽量 ≤ 90 个中文字符；key_points ≤ 3 条，tags ≤ 4 个。",
        "- 不要输出 evidence_chunk_ids、chunk_id、页码、引用或来源说明。",
        "",
        "输入文本片段:",
    ]
    for index, chunk in enumerate(batch, start=1):
        lines.append(f"片段 {index}: {chunk_prompt_text(chunk)}")
    return "\n".join(lines)
