"""Prompts for map-reduce note generation.

Adapted from the donor's course-section / course-summary prompts. The map step
generates one grounded section per topic subgraph; the reduce step writes the
导读 summary. New vs. donor: each section prompt carries the原文 chunks the topic
was retrieved against, so the section can be grounded in real source text.
"""
from __future__ import annotations

from corpus2node.core.text import normalize_text
from corpus2node.core.types import ConceptNode, EvidenceChunk, GraphEdge

SECTION_SYSTEM_PROMPT = """\
你是知识图谱笔记分章生成器。你会读取围绕某个核心主题及其关联节点的局部图谱数据，外加若干原文片段，专门为这个主题生成一节结构化、可复习的详细笔记。

要求：
- 围绕提供的核心主题和关联节点详细展开，把各个概念的定义、公式、相互关系交代清楚。
- 不要写整本总复习或整体总结，专注写透这一个主题。
- 严格控制本节边界：前文已讲过的概念只做一句话承接，不要重复定义、重复公式或重复长段解释。
- 可以使用提供的原文片段补充准确细节，但不要编造图谱与原文之外的内容；不要在正文里写引用、页码、来源、chunk_id。
- content_md 格式：
  - 以 1-2 句引入开头，说明本节定位或引出核心问题。
  - 重要术语加粗，列举用 - 分点（每条 1-2 句，不可再分），对比内容用 Markdown 表格（列名加粗）。
  - 只用加粗 **...** 作为段内小标题，不要使用 ##、### 或任何 Markdown 标题语法，不要使用编号列表。
  - 末尾至少包含 **关键结论**、**学习路径**、**易混点** 之一，用 - 分点列出。
  - 公式使用块级 KaTeX（$$ ... $$），保留正确换行；不要为形式硬凑公式。
  - 末尾不写"以上就是本节内容"等空洞总结语。
- title 格式为"章节标题：副标题"，不加编号，聚焦本节核心概念，避免"其他概念/补充内容"这类空泛标题。
- 只返回 JSON object：{"title":"章节标题：副标题","content_md":"Markdown正文","concept_ids":["concept:id"]}
"""

SUMMARY_SYSTEM_PROMPT = """\
你是知识图谱笔记导读生成器。你会读取笔记标题和已生成的章节标题，为整份笔记生成一段总览段落。

要求：
- 写一段无标题的总览段落，概括本份资料主线、各章节内容及建议学习路径，150-200字。
- 不要使用任何标题（##等）、编号或分点，写成连贯段落。
- 不要重复输出章节正文，不要编造章节标题之外的新知识点。
- 只返回 JSON object：{"summary":"总览段落"}
"""


def build_section_prompt(
    *,
    lecture_title: str,
    topic_pref: str,
    section_index: int,
    total_sections: int,
    core_name: str,
    concepts: list[ConceptNode],
    edges: list[GraphEdge],
    grounding_chunks: list[EvidenceChunk],
    covered_concepts: list[str],
) -> str:
    concept_by_id = {concept.concept_id: concept for concept in concepts}
    lines = [
        f"资料：{lecture_title}",
        f"用户主题偏好：{normalize_text(topic_pref) or '无，按图谱生成'}",
        f"章节位置：第 {section_index} 节 / 共 {total_sections} 节",
        f"本节核心概念：{core_name}",
        f"前文已重点讲过的概念：{_format_covered(covered_concepts)}",
        "",
        "本节图谱节点：",
    ]
    for index, concept in enumerate(concepts):
        role = "core" if index == 0 else "neighbor"
        parts = [
            f"role={role}",
            f"id={concept.concept_id}",
            f"name={concept.name}",
            f"importance_score={concept.importance_score:.4f}",
        ]
        if concept.graph_metrics:
            parts.append(
                "graph_metrics="
                + "；".join(f"{key}={value:.4f}" for key, value in sorted(concept.graph_metrics.items()))
            )
        if concept.definition:
            parts.append(f"definition={concept.definition[:260]}")
        if concept.summary:
            parts.append(f"summary={concept.summary[:320]}")
        if concept.key_points:
            parts.append(f"key_points={'；'.join(concept.key_points[:6])}")
        if concept.prerequisites:
            parts.append(f"prerequisites={'；'.join(concept.prerequisites[:6])}")
        if concept.applications:
            parts.append(f"applications={'；'.join(concept.applications[:6])}")
        lines.append("- " + " | ".join(parts))

    lines.extend(["", "关系边："])
    rendered_edges = 0
    for edge in edges:
        source = concept_by_id.get(edge.source)
        target = concept_by_id.get(edge.target)
        if source is None or target is None:
            continue
        relation_type = edge.properties.get("relation_type") or _edge_type_value(edge.edge_type)
        lines.append(f"- {source.name} -> {target.name} ({relation_type})")
        rendered_edges += 1
    if rendered_edges == 0:
        lines.append("- 无显式关系边时，请根据节点定义和 key_points 组织本节，但不要编造图谱外知识。")

    if grounding_chunks:
        lines.extend(["", "原文片段（可据此补充准确细节，不要逐字照抄，不要写来源/页码）："])
        for chunk in grounding_chunks:
            text = normalize_text(chunk.text)[:360]
            if text:
                lines.append(f"- {text}")

    lines.extend(
        [
            "",
            "生成要求：",
            "- 只生成这一节，不要生成整本总览或结语。",
            "- 围绕核心概念展开，把关联节点写成解释、对比、前置关系、组成关系或应用位置。",
            "- concept_ids 必须使用上面给出的 id，至少包含核心概念 id，且不要重复。",
            "- 末尾至少包含 **关键结论**、**学习路径**、**易混点** 之一。",
        ]
    )
    return "\n".join(lines)


def build_summary_prompt(*, lecture_title: str, topic_pref: str, section_titles: list[str]) -> str:
    lines = [
        f"资料：{lecture_title}",
        f"用户主题偏好：{normalize_text(topic_pref) or '无'}",
        "",
        "已经生成的章节标题：",
    ]
    lines.extend(f"{index}. {title}" for index, title in enumerate(section_titles, start=1))
    lines.extend(
        [
            "",
            "请生成整份笔记的导读 summary，150-200字，重点说明阅读顺序和章节主线。",
            "只返回 JSON：{\"summary\":\"\"}",
        ]
    )
    return "\n".join(lines)


def _format_covered(concepts: list[str], *, limit: int = 24) -> str:
    unique: list[str] = []
    seen: set[str] = set()
    for concept in concepts:
        name = normalize_text(concept)
        key = name.lower()
        if not name or key in seen:
            continue
        unique.append(name)
        seen.add(key)
        if len(unique) >= limit:
            break
    return "、".join(unique) if unique else "无"


def _edge_type_value(edge_type) -> str:
    return edge_type.value if hasattr(edge_type, "value") else str(edge_type)
