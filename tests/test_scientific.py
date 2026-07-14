from __future__ import annotations

import asyncio
import uuid

from fastapi.testclient import TestClient

from corpus2node.api.app import app
from corpus2node.core.types import CourseSession, EvidenceChunk, IngestArtifact, SessionStatus, SourceKind
from corpus2node.scientific.engine import (
    _extract_paper,
    _load_paper_input,
    _synthesize_map_reduce,
    run_scientific_analysis,
)
from corpus2node.scientific.schemas import (
    LLMCrossPaperInsight,
    LLMCrossPaperSynthesis,
    LLMDecisionCard,
    LLMPaperClaim,
    LLMPaperEntity,
    LLMPaperExperiment,
    LLMPaperExtraction,
    LLMPaperMetricResult,
    LLMPaperRelation,
    ScientificAnalysisRequest,
    ScientificInsightType,
    ScientificLanguageMode,
    ScientificEvidenceMatrixRow,
    ScientificPaperProfile,
    ScientificReport,
)
from corpus2node.storage import local

client = TestClient(app)


def test_scientific_large_project_uses_batched_map_reduce():
    session_ids = [uuid.uuid4() for _ in range(41)]
    papers = [
        ScientificPaperProfile(
            session_id=session_id,
            source_title=f"Paper {index}",
            title_zh=f"论文 {index}",
            research_problem_zh="问题",
            method_summary_zh="方法",
            result_summary_zh="结果",
        )
        for index, session_id in enumerate(session_ids)
    ]
    matrix = [
        ScientificEvidenceMatrixRow(
            paper_title=value.title_zh,
            session_id=value.session_id,
            research_problem_zh=value.research_problem_zh,
        )
        for value in papers
    ]
    prompts: list[str] = []

    async def caller(prompt: str) -> LLMCrossPaperSynthesis:
        prompts.append(prompt)
        return LLMCrossPaperSynthesis(title_zh=f"阶段 {len(prompts)}")

    result = asyncio.run(
        _synthesize_map_reduce(caller, papers, [], [], matrix, objective_zh="大规模证据综合")
    )
    assert len(prompts) == 4  # 3 map batches + 1 reduce
    assert '"paper_count": 41' in prompts[-1]
    assert result.title_zh == "阶段 1"


def _seed_paper(title: str, text: str) -> uuid.UUID:
    session = CourseSession(
        course_title="demo: papers",
        lecture_title=title,
        status=SessionStatus.graph_ready,
    )
    local.save_session(session)
    source_id = uuid.uuid4()
    chunks = [
        EvidenceChunk(
            chunk_id=f"{title.lower()}-chunk-{index}",
            source_id=str(source_id),
            source_type=SourceKind.pdf,
            text=f"{text} 实验片段 {index}。",
            summary=text,
            page_start=index + 1,
        )
        for index in range(3)
    ]
    local.save_ingest_artifact(
        IngestArtifact(
            session_id=session.session_id,
            source_id=source_id,
            source_kind=SourceKind.pdf,
            chunks=chunks,
        )
    )
    return session.session_id


def _paper_output(name: str) -> LLMPaperExtraction:
    return LLMPaperExtraction(
        title_zh=f"{name}：协作价值分解",
        title_original=name,
        research_problem_zh="在集中训练、分散执行条件下学习协作策略。",
        method_summary_zh="将团队价值函数按约束方式分解到智能体价值函数。",
        result_summary_zh="该方法在论文给定环境中改善了协作学习表现。",
        limitations_zh=["证据只覆盖论文所报告的实验环境。"],
        entities=[
            LLMPaperEntity(
                entity_type="method",
                name_zh="价值分解",
                name_en="Value Decomposition",
                canonical_name="value decomposition",
                description_zh="把团队价值与个体价值建立结构约束。",
                evidence_ids=["C01", "BAD"],
            )
        ],
        relations=[
            LLMPaperRelation(
                source_name=name,
                relation_type="使用",
                target_name="价值分解",
                statement_zh=f"{name} 使用价值分解学习协作策略。",
                evidence_ids=["C01"],
            )
        ],
        claims=[
            LLMPaperClaim(
                claim_type="实验结果",
                statement_zh=f"{name} 在论文实验中显示出协作学习能力。",
                statement_original=f"{name} learns cooperative policies.",
                evidence_quote=name,
                subject=name,
                predicate_zh="显示",
                object="协作学习能力",
                modality="observed",
                evidence_ids=["C01", "NOT_REAL"],
            ),
            LLMPaperClaim(
                claim_type="无效主张",
                statement_zh="这条主张没有真实证据。",
                evidence_ids=["NOT_REAL"],
            ),
            LLMPaperClaim(
                claim_type="伪造引文",
                statement_zh="这条主张引用了不存在于原文的文字。",
                evidence_quote="fabricated verbatim quote",
                evidence_ids=["C01"],
            ),
        ],
        experiments=[
            LLMPaperExperiment(
                name_zh="协作任务评估",
                methods=[name],
                datasets_or_environments=["协作多智能体环境"],
                baselines=["独立学习"],
                conditions_zh="使用论文报告的集中训练设置。",
                metrics=[
                    LLMPaperMetricResult(
                        metric_name="团队回报",
                        comparison_zh="与基线比较团队回报。",
                        evidence_quote=name,
                        evidence_ids=["C02"],
                    ),
                    LLMPaperMetricResult(
                        metric_name="伪造指标",
                        value="999",
                        evidence_quote="fabricated numeric quote",
                        evidence_ids=["C02"],
                    ),
                ],
                conclusion_zh="该方法在给定设置中有效。",
                evidence_ids=["C01"],
            )
        ],
    )


def test_scientific_analysis_builds_grounded_cross_paper_report():
    left = _seed_paper("VDN", "VDN 通过加和分解团队价值函数。")
    right = _seed_paper("QMIX", "QMIX 通过单调混合网络表达团队价值函数。")

    async def paper_caller(prompt: str) -> LLMPaperExtraction:
        return _paper_output("VDN" if "VDN" in prompt else "QMIX")

    left_evidence = f"ev:{str(left)[:8]}:vdn-chunk-0"
    right_evidence = f"ev:{str(right)[:8]}:qmix-chunk-0"

    async def synthesis_caller(prompt: str) -> LLMCrossPaperSynthesis:
        assert "研发分析目标" in prompt
        return LLMCrossPaperSynthesis(
            title_zh="VDN 与 QMIX 的协作价值分解证据分析",
            insights=[
                LLMCrossPaperInsight(
                    insight_type=ScientificInsightType.technical_lineage,
                    title_zh="从加和分解到单调混合",
                    summary_zh="两篇论文沿着更灵活的价值分解约束形成技术演进。",
                    reasoning_zh="两者解决相同协作学习问题，但团队价值组合方式不同。",
                    related_session_ids=[left, right],
                    evidence_ids=[left_evidence, right_evidence, "invented"],
                )
            ],
            decision_cards=[
                LLMDecisionCard(
                    title_zh="先验证价值分解约束",
                    recommendation_zh="在目标环境中并行复现两类组合方式。",
                    rationale_zh="现有证据表明组合约束是两条技术路线的关键差异。",
                    next_experiment_zh="固定训练预算，对比加和与单调混合的团队回报和稳定性。",
                    risks_zh=["环境差异可能削弱论文结论的可迁移性。"],
                    evidence_ids=[left_evidence, right_evidence],
                )
            ],
        )

    report = asyncio.run(
        run_scientific_analysis(
            ScientificAnalysisRequest(session_ids=[left, right], objective_zh="选择协作价值分解路线"),
            paper_caller=paper_caller,
            synthesis_caller=synthesis_caller,
        )
    )

    assert len(report.papers) == 2
    assert len(report.claims) == 2
    assert len(report.experiments) == 2
    assert all(len(experiment.metrics) == 1 for experiment in report.experiments)
    assert len(report.conditions) == 2
    assert {value.relation_type.value for value in report.nary_relations} >= {"EVALUATED_ON", "SUPPORTS"}
    assert all(value.experiment_ids for value in report.nary_relations)
    assert all(value.evidence_ids for value in report.nary_relations)
    assert len(report.evidence_matrix) == 2
    assert report.insights[0].evidence_ids == [left_evidence, right_evidence]
    assert report.decision_cards[0].next_experiment_zh
    valid_ids = {evidence.evidence_id for evidence in report.evidence}
    assert valid_ids
    assert all(set(claim.evidence_ids) <= valid_ids for claim in report.claims)
    assert all(claim.evidence_quote in {"VDN", "QMIX"} for claim in report.claims)
    assert all(evidence.locator.startswith("原始文献 · 第") for evidence in report.evidence)
    assert local.load_scientific_report(report.report_id).title_zh == report.title_zh


def test_scientific_extraction_cache_tracks_prompt_model_and_schema(monkeypatch):
    session_id = _seed_paper("VDN", "VDN 通过加和分解团队价值函数。")
    item = _load_paper_input(session_id)
    calls = 0

    async def paper_caller(prompt: str) -> LLMPaperExtraction:
        nonlocal calls
        calls += 1
        return _paper_output("VDN")

    asyncio.run(_extract_paper(item, paper_caller, ScientificLanguageMode.zh_bilingual))
    asyncio.run(_extract_paper(item, paper_caller, ScientificLanguageMode.zh_bilingual))
    assert calls == 1

    monkeypatch.setattr(
        "corpus2node.scientific.engine.PAPER_EXTRACTION_SYSTEM_PROMPT",
        "changed extraction prompt",
    )
    asyncio.run(_extract_paper(item, paper_caller, ScientificLanguageMode.zh_bilingual))
    assert calls == 2


def test_scientific_report_routes_list_get_and_delete(monkeypatch):
    session_id = _seed_paper("VDN", "有证据的论文片段。")
    report = ScientificReport(title_zh="科研证据报告", session_ids=[session_id])

    async def fake_run(request: ScientificAnalysisRequest) -> ScientificReport:
        assert request.session_ids == [session_id]
        local.save_scientific_report(report)
        return report

    monkeypatch.setattr("corpus2node.api.routes.scientific.run_scientific_analysis", fake_run)
    response = client.post("/scientific/run", json={"session_ids": [str(session_id)]})
    assert response.status_code == 200
    assert response.json()["report_id"] == report.report_id
    assert client.get(f"/scientific/{report.report_id}").status_code == 200
    assert any(item["report_id"] == report.report_id for item in client.get("/scientific").json())
    assert client.delete(f"/scientific/{report.report_id}").json() == {"ok": True}
    assert client.get(f"/scientific/{report.report_id}").status_code == 404


def test_scientific_stream_runs_as_a_detached_replayable_job(monkeypatch):
    session_id = _seed_paper("VDN", "有证据的论文片段。")
    report = ScientificReport(title_zh="流式科研报告", session_ids=[session_id])

    async def fake_run(request: ScientificAnalysisRequest) -> ScientificReport:
        local.save_scientific_report(report)
        return report

    monkeypatch.setattr("corpus2node.api.routes.scientific.run_scientific_analysis", fake_run)
    response = client.post(
        "/scientific/run/stream",
        json={"session_ids": [str(session_id)], "objective_zh": "stream"},
    )
    assert response.status_code == 200
    assert '"type": "start"' in response.text
    assert '"type": "done"' in response.text
    assert report.report_id in response.text


def test_paper_schema_normalizes_common_json_mode_variants():
    value = LLMPaperExtraction.model_validate(
        {
            "paper_title": "论文标题",
            "limitations_zh": "",
            "entities": [{"id": "E1", "type": "method", "name_zh": "方法", "description": "中文说明"}],
            "relations": [{"source_id": "E1", "target_id": "E2", "relation_type": "使用", "confidence": "高"}],
            "claims": [{"claim_type": "结果", "statement": "中文结论", "statement_original": None, "polarity": "正面", "modality": "已证实", "confidence": "85%"}],
            "experiments": [{"description": "对比实验", "datasets_or_environments": "环境A", "metrics": [{"metric_name": "胜率", "value": None}, {"metric_name": "回报", "value": -22.2}], "results": "更好", "evidence_ids": ["C01"]}],
        }
    )
    assert value.title_zh == "论文标题"
    assert value.limitations_zh == []
    assert value.entities[0].description_zh == "中文说明"
    assert value.relations[0].confidence == 0.85
    assert value.claims[0].statement_zh == "中文结论"
    assert value.claims[0].polarity == "positive"
    assert value.claims[0].statement_original == ""
    assert value.claims[0].modality == "observed"
    assert value.experiments[0].metrics[0].metric_name == "胜率"
    assert value.experiments[0].datasets_or_environments == ["环境A"]
    assert value.experiments[0].metrics[0].value == ""
    assert value.experiments[0].metrics[1].value == "-22.2"


def test_cross_schema_normalizes_common_json_mode_variants():
    value = LLMCrossPaperSynthesis.model_validate(
        {
            "cross_paper_findings": [{
                "type": "technology_transfer",
                "description_zh": "中文洞察",
                "explanation_zh": "中文推理",
            }],
            "decision_cards": [{
                "title_zh": "验证路线",
                "decision_zh": "先进行统一条件对比。",
                "context_zh": "当前论文实验条件不同。",
                "next_experiment_zh": "固定预算完成对照实验。",
                "risk_and_mitigation_zh": "任务构造可能偏离论文条件。",
                "evidence_refs": ["ev:1"],
            }],
        }
    )
    assert value.insights[0].insight_type == ScientificInsightType.transfer_opportunity
    assert value.insights[0].summary_zh == "中文洞察"
    assert value.insights[0].reasoning_zh == "中文推理"
    assert value.decision_cards[0].recommendation_zh == "先进行统一条件对比。"
    assert value.decision_cards[0].rationale_zh == "当前论文实验条件不同。"
    assert value.decision_cards[0].risks_zh == ["任务构造可能偏离论文条件。"]
    assert value.decision_cards[0].evidence_ids == ["ev:1"]


def test_empty_cross_synthesis_gets_grounded_deterministic_fallback():
    left = _seed_paper("VDN", "VDN 通过加和分解团队价值函数。")
    right = _seed_paper("QMIX", "QMIX 通过单调混合网络表达团队价值函数。")

    async def paper_caller(prompt: str) -> LLMPaperExtraction:
        return _paper_output("VDN" if "VDN" in prompt else "QMIX")

    async def empty_synthesis(prompt: str) -> LLMCrossPaperSynthesis:
        return LLMCrossPaperSynthesis()

    report = asyncio.run(
        run_scientific_analysis(
            ScientificAnalysisRequest(session_ids=[left, right]),
            paper_caller=paper_caller,
            synthesis_caller=empty_synthesis,
        )
    )
    assert {item.insight_type for item in report.insights} == {
        ScientificInsightType.technical_lineage,
        ScientificInsightType.research_gap,
    }
    assert report.decision_cards[0].next_experiment_zh
    valid = {item.evidence_id for item in report.evidence}
    assert set(report.decision_cards[0].evidence_ids) <= valid
