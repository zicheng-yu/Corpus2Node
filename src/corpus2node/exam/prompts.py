"""Prompts for importance-driven level-test generation + independent verification.

The application chooses target concepts deterministically from graph importance;
the model chooses the most suitable question form for each target. `exclude_stems`
lets top-up rounds ask for different questions. The solver independently verifies
answers against graph concepts and source chunks.
"""
from __future__ import annotations

from corpus2node.core.text import normalize_text
from corpus2node.core.types import ConceptNode, EvidenceChunk, ExamQuestion, GraphArtifact

EXAM_DETAILED_CONCEPT_LIMIT = 56
EXAM_MAX_EDGE_LINES = 120

QUESTION_TYPE_LABEL = {
    "single_choice": "单选题",
    "multiple_choice": "多选题",
    "true_false": "判断题",
    "fill_blank": "填空题",
    "short_answer": "简答题",
    "essay": "论述题",
}

EXAM_SYSTEM_PROMPT = """\
你是知识图谱水平测试生成器。你会读取当前资料的知识图谱与指定的知识点测试计划，生成一份结构化水平测试。

要求：
- 只基于当前图谱生成测试题，不接入 Web Search，不使用外部资料。
- 严格覆盖测试计划指定的主知识点，不自行替换为低重要度知识点。
- 每题必须有答案和解析，解析要能帮助学生复习。
- 输出必须是 JSON object，不要 Markdown、来源、页码、引用、chunk_id。
"""

EXAM_STYLE_RULES = """\
水平测试规则：
- 主知识点已由系统按 importance_score 确定；每题必须覆盖对应的主知识点。
- 高 betweenness_centrality 概念用于综合题，考察跨模块连接。
- 高重要度的前置概念用于基础题；关系密集概念用于辨析题。
- 根据知识点性质自动选择最能判断掌握水平的形式，不要求用户选择题型。
- 整体兼顾识记、理解、应用与综合，避免全部使用同一种形式。
- 每题必须包含题干、形式、答案、解析、难度、关联概念和考察点。
- question_type 可使用：single_choice / multiple_choice / true_false / fill_blank / short_answer / essay。
- 选择题干扰项应来自相近概念或常见混淆，不随机编造。
- 单选题和多选题必须提供 4 个选项，choice_id 使用 A/B/C/D。
- 判断题答案为"正确"或"错误"。
- 填空题答案必须可精确判定；多个等价答案用"；"分隔。
- 简答题答案简洁，解析说明评分点；论述题考察跨概念综合，答案给分点要点。
- 不为形式强行出公式题；只有图谱内容包含数学结论时才出公式相关题。
- 输出必须是 JSON object，不要 Markdown、来源、页码、引用、chunk_id。
"""

SOLVER_SYSTEM_PROMPT = """\
你是独立答题验证器。你只能依据给定的图谱概念与原文片段作答，不得使用任何外部知识。

要求：
- 给出你的答案：单选给选项字母（如 A），多选给字母组合（如 ABD），判断给"正确"或"错误"，填空给标准答案，简答/论述给要点。
- grounded：当给定材料足以支撑你的答案时为 true，否则为 false。
- 不要参考题目可能自带的答案，独立推理。
- 只返回 JSON：{"answer":"","grounded":true,"reasoning":""}
"""


def build_exam_prompt(
    graph: GraphArtifact,
    *,
    lecture_title: str,
    target_concepts: list[ConceptNode],
    exclude_stems: list[str] | None = None,
) -> str:
    concept_by_id = {concept.concept_id: concept for concept in graph.concepts}
    sorted_concepts = sorted(graph.concepts, key=lambda item: item.importance_score, reverse=True)
    detailed = sorted_concepts[:EXAM_DETAILED_CONCEPT_LIMIT]
    detailed_ids = {concept.concept_id for concept in detailed}

    lines = [
        f"资料：{lecture_title}",
        f"题目数量：{len(target_concepts)}",
        "",
        EXAM_STYLE_RULES.strip(),
        "",
        "请输出 JSON：",
        '{"title":"","summary":"","questions":[{"question_type":"single_choice","stem":"","choices":[{"choice_id":"A","text":""},{"choice_id":"B","text":""},{"choice_id":"C","text":""},{"choice_id":"D","text":""}],"answer":"","explanation":"","difficulty":"medium","concept_ids":["concept:id"],"tested_points":[""],"importance_basis":""}]}',
        "",
        "图谱聚类：",
    ]
    for cluster in graph.topic_clusters:
        names = [concept_by_id[cid].name for cid in cluster.concept_ids if cid in concept_by_id]
        lines.append(f"- {cluster.cluster_id} {cluster.title}: {'、'.join(names)}")

    lines.extend(["", "高优先级概念："])
    for concept in detailed:
        lines.append("- " + _concept_line(concept, definition_chars=180, summary_chars=220, points=4))

    remaining = [concept for concept in sorted_concepts if concept.concept_id not in detailed_ids]
    if remaining:
        lines.extend(["", "其余概念目录："])
        for concept in remaining:
            parts = [f"id={concept.concept_id}", f"name={concept.name}", f"importance_score={concept.importance_score:.4f}"]
            if concept.definition:
                parts.append(f"definition={concept.definition[:80]}")
            lines.append("- " + " | ".join(parts))

    lines.extend(["", "关系边（用于设计综合题、辨析题和干扰项）："])
    ranked_edges = sorted(
        graph.edges,
        key=lambda edge: _edge_importance(edge, concept_by_id),
        reverse=True,
    )
    for edge in ranked_edges[:EXAM_MAX_EDGE_LINES]:
        source = concept_by_id.get(edge.source)
        target = concept_by_id.get(edge.target)
        if source is None or target is None:
            continue
        relation_type = edge.properties.get("relation_type") or _edge_type_value(edge.edge_type)
        lines.append(f"- {source.name} -> {target.name} ({relation_type})")

    if exclude_stems:
        lines.extend(["", "请避免与以下已出题目重复（出不同的题）："])
        lines.extend(f"- {normalize_text(stem)[:80]}" for stem in exclude_stems[:40])

    lines.extend(["", "知识点测试计划（顺序可调整，但每项必须恰好生成一题）："])
    for index, concept in enumerate(target_concepts, start=1):
        lines.append(
            f"- 计划{index}: primary_concept_id={concept.concept_id} | "
            f"name={concept.name} | importance_score={concept.importance_score:.4f}"
        )

    lines.extend(
        [
            "",
            "生成要求：",
            f"- 生成恰好 {len(target_concepts)} 道题，与知识点测试计划一一对应。",
            "- 每题 concept_ids 必须包含对应计划的 primary_concept_id，并把它放在第一位。",
            "- concept_ids 必须使用上面给出的 concept:id。",
            "- importance_basis 用一句话说明主知识点为何值得测试。",
            "- title 和 summary 使用“水平测试”或“测试”，不要使用“试卷”。",
        ]
    )
    return "\n".join(lines)


def build_solver_prompt(
    question: ExamQuestion,
    *,
    concepts: list[ConceptNode],
    grounding_chunks: list[EvidenceChunk],
) -> str:
    lines = [
        f"题型：{QUESTION_TYPE_LABEL.get(question.question_type, question.question_type)}",
        f"题干：{question.stem}",
    ]
    if question.choices:
        lines.append("选项：")
        lines.extend(f"{choice.choice_id}. {choice.text}" for choice in question.choices)

    lines.extend(["", "可用图谱概念："])
    for concept in concepts:
        parts = [f"name={concept.name}"]
        if concept.definition:
            parts.append(f"definition={concept.definition[:220]}")
        if concept.key_points:
            parts.append(f"key_points={'；'.join(concept.key_points[:4])}")
        lines.append("- " + " | ".join(parts))
    if not concepts:
        lines.append("- （无）")

    if grounding_chunks:
        lines.extend(["", "原文片段："])
        for chunk in grounding_chunks:
            text = normalize_text(chunk.text)[:300]
            if text:
                lines.append(f"- {text}")

    lines.extend(["", "请只依据以上材料独立作答，并按 JSON 格式返回 answer / grounded / reasoning。"])
    return "\n".join(lines)


def _concept_line(concept: ConceptNode, *, definition_chars: int, summary_chars: int, points: int) -> str:
    parts = [
        f"id={concept.concept_id}",
        f"name={concept.name}",
        f"canonical={concept.canonical_name}",
        f"importance_score={concept.importance_score:.4f}",
    ]
    if concept.graph_metrics:
        parts.append(
            "graph_metrics=" + "，".join(f"{key}={value:.4f}" for key, value in sorted(concept.graph_metrics.items()))
        )
    if concept.definition:
        parts.append(f"definition={concept.definition[:definition_chars]}")
    if concept.summary:
        parts.append(f"summary={concept.summary[:summary_chars]}")
    if concept.key_points:
        parts.append(f"key_points={'；'.join(concept.key_points[:points])}")
    if concept.prerequisites:
        parts.append(f"prerequisites={'、'.join(concept.prerequisites[:points])}")
    if concept.applications:
        parts.append(f"applications={'、'.join(concept.applications[:points])}")
    return " | ".join(parts)


def _edge_importance(edge, concept_by_id) -> float:
    source = concept_by_id.get(edge.source)
    target = concept_by_id.get(edge.target)
    return (source.importance_score if source else 0.0) + (target.importance_score if target else 0.0)


def _edge_type_value(edge_type) -> str:
    return edge_type.value if hasattr(edge_type, "value") else str(edge_type)
