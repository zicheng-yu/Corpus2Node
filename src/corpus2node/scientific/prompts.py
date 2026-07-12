from __future__ import annotations

import json

from corpus2node.core.types import CourseSession, EvidenceChunk
from corpus2node.scientific.schemas import ScientificLanguageMode


SCIENTIFIC_LANGUAGE_POLICY = """\
语言规则（必须遵守）：
- 所有解释、判断、摘要、关系描述、局限和建议一律使用简体中文完整句子。
- 论文标题、算法、模型、数据集、材料、指标的正式英文名称不要硬译；分别写入 name_en、title_original 或原文字段。
- name_zh 使用准确中文名称，name_en 保留正式英文名称；若没有可靠中文译名，name_zh 可写通行英文专名，但不要在中文句子中无规律夹杂英文长句。
- statement_original 只在需要保留原论文关键表述时填写；其他说明字段禁止整句英文。
"""

PAPER_EXTRACTION_SYSTEM_PROMPT = f"""\
你是面向企业研发决策的科技文献证据抽取器。你的任务不是写泛泛的论文摘要，而是把单篇科技论文拆成可核查的证据单元：研究问题、方法/模型、数据集或实验环境、指标、实验结果、限制、主张，以及它们之间的关系。

{SCIENTIFIC_LANGUAGE_POLICY}
证据规则（必须遵守）：
- 只能依据用户提供的论文片段，不得补充外部知识或常识性结论。
- 每个实体、关系、主张和实验至少引用一个提供的证据编号（如 C01）；没有证据就不要输出。
- 数值、比较关系、优于/弱于、因果、限制等结论必须由对应片段直接支持。
- evidence_ids 只能使用输入中真实存在的 Cxx 编号，禁止编造 chunk_id。
- relation_type 只能使用以下受控类型：PROPOSES、EXTENDS、USES、EVALUATED_ON、MEASURED_BY、REPORTS_RESULT、OUTPERFORMS、SUPPORTS、CONTRADICTS、REPLICATES、LIMITED_BY、REQUIRES、DERIVED_FROM、RELATED_TO。
- “A 优于 B”必须进入同一个实验记录：methods 写 A，baselines 写 B，metrics 写指标、数值、单位和比较结论，conditions_zh 写实验条件；不可只输出一条孤立二元边。
- 主张 claim_type 使用简短中文分类，如“方法贡献”“实验结果”“理论性质”“局限性”。
- 提取重要且可决策的内容，避免把作者姓名、章节标题、一般背景词当实体。
- 只返回符合 schema 的 JSON object。

字段名必须严格使用：
- 顶层：title_zh、title_original、research_problem_zh、method_summary_zh、result_summary_zh、limitations_zh、entities、relations、claims、experiments。
- 实体：entity_type、name_zh、name_en、canonical_name、description_zh、evidence_ids。
- 关系：source_name、relation_type、target_name、statement_zh、confidence、evidence_ids；不要使用 source_id/target_id。
- 主张：claim_type、statement_zh、statement_original、subject、predicate_zh、object、polarity、modality、confidence、evidence_ids。
- 实验：name_zh、methods、datasets_or_environments、baselines、conditions_zh、metrics、conclusion_zh、evidence_ids；metrics 每项必须是包含 metric_name、value、unit、comparison_zh、evidence_ids 的 object，不能只写字符串。
"""

CROSS_PAPER_SYSTEM_PROMPT = f"""\
你是企业研发决策分析师。你会收到多篇论文的结构化证据，任务是进行跨论文证据综合，识别：一致证据、明确矛盾、研究空白、技术迁移机会和技术演进关系，并形成可执行的研发决策卡。

{SCIENTIFIC_LANGUAGE_POLICY}
推理规则（必须遵守）：
- 只能使用输入中的论文、主张和证据，不得引入外部事实。
- “矛盾”必须是相近条件下对同一问题出现不兼容结论；条件不同只能写成边界差异，不能夸大为矛盾。
- “研究空白”必须指出现有证据没有覆盖的变量、场景、对照或评价维度，不得把未知包装成事实。
- “技术迁移机会”必须明确来源能力、目标场景、最小验证实验和风险。
- 每条洞察至少关联两篇论文；supporting_claim_ids 与 evidence_ids 必须来自输入。
- 每张决策卡必须有可执行的 next_experiment_zh，并引用证据。
- 所有正文使用中文，正式英文名称只作为专名保留。
- 只返回符合 schema 的 JSON object。
"""


def build_paper_extraction_prompt(
    session: CourseSession,
    chunks: list[tuple[str, EvidenceChunk, str]],
    *,
    language_mode: ScientificLanguageMode,
) -> str:
    mode = "中文叙述，正式英文名称在独立字段保留" if language_mode == ScientificLanguageMode.zh_bilingual else "全部中文"
    lines = [
        f"资料集标题：{session.lecture_title}",
        f"输出语言模式：{mode}",
        "请抽取论文级证据结构。每条记录必须引用下面的证据编号。",
        "",
        "论文片段：",
    ]
    for alias, chunk, locator in chunks:
        text = " ".join(chunk.text.split())
        lines.append(f"[{alias}] {locator} | {text}")
    return "\n".join(lines)


def build_cross_paper_prompt(payload: dict, *, objective_zh: str) -> str:
    objective = objective_zh.strip() or "比较论文的技术路线、实验结论与局限，发现研发机会"
    return "\n".join(
        [
            f"研发分析目标：{objective}",
            "请基于以下结构化论文证据生成跨论文洞察与研发决策卡。",
            "输入 JSON 中的 evidence_ids 已经是真实可定位证据；不得创造新的编号。",
            "",
            json.dumps(payload, ensure_ascii=False, indent=2),
        ]
    )
