from __future__ import annotations

import json

import httpx
import pytest
from fastapi.testclient import TestClient

from corpus2node.api.app import app
from corpus2node.core.types import CourseSession, SourceFile, SourceKind
from corpus2node.scientific.evaluation import (
    GoldReviewStatus,
    _bbox_match,
    evaluate_gold_corpus,
    evaluate_paper,
    load_gold_directory,
)
from corpus2node.scientific.parsers import parse_grobid_pdf, parse_jats_xml, parse_tei_xml
from corpus2node.storage import local

client = TestClient(app)


JATS = """<?xml version="1.0"?>
<article xmlns:xlink="http://www.w3.org/1999/xlink">
  <front><article-meta><title-group><article-title>测试论文</article-title></title-group></article-meta></front>
  <body><sec id="intro"><title>Introduction</title>
    <p>First result is reported.<xref ref-type="bibr" rid="R1">[1]</xref> It is reproducible.</p>
    <sec id="method"><title>Method</title><p>The method uses CTDE.</p></sec>
  </sec>
  <table-wrap id="T1"><label>Table 1</label><caption><p>Results</p></caption><table>
    <tr><th>Method</th><th>Score</th></tr><tr><td>Ours</td><td>83.2</td></tr>
  </table></table-wrap>
  <disp-formula id="F1"><mml:math xmlns:mml="http://www.w3.org/1998/Math/MathML"><mml:mi>x</mml:mi></mml:math></disp-formula></body>
  <back><ref-list><ref id="R1"><element-citation><article-title>Prior</article-title></element-citation></ref></ref-list></back>
</article>"""

TEI = """<TEI xmlns="http://www.tei-c.org/ns/1.0">
  <teiHeader><fileDesc><titleStmt><title>GROBID Paper</title></titleStmt></fileDesc></teiHeader>
  <facsimile><surface xml:id="page-1" lrx="612" lry="792"/></facsimile>
  <text><body><div xml:id="d1"><head>Experiments</head><p coords="1,10,20,100,12">
    <s xml:id="s1" coords="1,10,20,100,12">Ours reaches 83.2.<ref type="bibr" target="#b1">[1]</ref></s>
  </p></div>
  <figure xml:id="tab1" type="table" coords="1,20,200,300,80"><head>Table 1</head><table><row><cell>Method</cell><cell>Score</cell></row></table></figure>
  <formula xml:id="f1" coords="1,30,300,120,20">x = 1</formula></body></text>
  <listBibl><biblStruct xml:id="b1"/></listBibl>
</TEI>"""


def test_jats_parser_preserves_sections_sentences_tables_and_formulas():
    document = parse_jats_xml(JATS, source_id="source-1")
    assert document.source_format == "jats"
    assert document.title == "测试论文"
    assert {section.title for section in document.sections} == {"Introduction", "Method"}
    intro = next(value for value in document.sections if value.title == "Introduction")
    assert intro.sentences[0].locator.citation_ids == ["R1"]
    assert document.tables[0].cells[3].text == "83.2"
    assert document.tables[0].cells[3].locator.table_row == 1
    assert document.formulas[0].formula_id == "F1"


def test_tei_parser_preserves_page_bbox_sentence_and_table_cell_locator():
    document = parse_tei_xml(TEI, source_id="source-2", from_grobid=True)
    sentence = document.sections[0].sentences[0]
    assert document.source_format == "grobid_tei"
    assert sentence.locator.page == 1
    assert sentence.locator.bboxes[0].width == 100
    assert sentence.locator.citation_ids == ["b1"]
    assert document.page_dimensions[1] == (612, 792)
    assert document.tables[0].cells[1].locator.table_column == 1
    assert document.tables[0].cells[1].locator.bboxes[0].width == 300
    assert document.formulas[0].locator.bboxes[0].y == 300


def test_bbox_matching_is_symmetric_and_one_to_one():
    from corpus2node.scientific.schemas import ScientificBBox

    box = ScientificBBox(page=1, x=10, y=20, width=100, height=12)
    assert _bbox_match([box], [box])
    assert not _bbox_match([box], [box, box])
    assert not _bbox_match([box, box], [box])


def test_grobid_client_requests_sentence_segmentation_and_coordinates(tmp_path):
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.4\nfixture")

    def handler(request: httpx.Request) -> httpx.Response:
        body = request.read()
        assert request.url.path == "/api/processFulltextDocument"
        assert b'segmentSentences' in body
        assert b'teiCoordinates' in body
        assert b'filename="paper.pdf"' in body
        return httpx.Response(200, content=TEI.encode(), headers={"content-type": "application/xml"})

    with httpx.Client(transport=httpx.MockTransport(handler), base_url="http://grobid") as client:
        document = parse_grobid_pdf(pdf, source_id="source-pdf", base_url="http://grobid", client=client)
    assert document.source_format == "grobid_tei"
    assert document.sections[0].sentences[0].locator.page == 1


def test_scientific_parse_route_persists_jats_document(tmp_path):
    xml_path = tmp_path / "paper.nxml"
    xml_path.write_text(JATS, encoding="utf-8")
    source = SourceFile(
        kind=SourceKind.document,
        filename="paper.nxml",
        content_type="application/xml",
        storage_path=str(xml_path),
        size_bytes=xml_path.stat().st_size,
    )
    session = CourseSession(course_title="papers", lecture_title="JATS", source_files=[source])
    local.save_session(session)
    response = client.post(
        "/scientific/parse",
        json={"session_id": str(session.session_id), "source_ids": [str(source.source_id)]},
    )
    assert response.status_code == 200
    assert response.json()[0]["source_format"] == "jats"
    stored = client.get(f"/scientific/documents/{session.session_id}")
    assert stored.status_code == 200
    assert stored.json()[0]["tables"][0]["table_id"] == "T1"


def test_formal_scientific_eval_uses_only_verified_gold(tmp_path):
    gold_dir = tmp_path / "gold"
    prediction_dir = tmp_path / "predictions"
    gold_dir.mkdir()
    prediction_dir.mkdir()
    base = {
        "schema_version": "1.0", "paper_id": "p1", "title": "Paper", "venue": "ICML", "year": 2025,
        "pdf_path": "paper.pdf", "annotators": ["a", "b"],
        "entities": [{"annotation_id": "e1", "entity_type": "method", "text": "QMIX"}],
        "relations": [{"annotation_id": "r1", "relation_type": "EVALUATED_ON", "roles": {"method": ["QMIX"], "dataset": ["SMAC"]}}],
        "claims": [{"annotation_id": "c1", "text": "QMIX improves win rate", "evidence_ids": ["ev1"]}],
        "numeric_results": [{"annotation_id": "n1", "metric": "win rate", "value": "83.20", "unit": "%", "condition": "SMAC", "evidence_ids": ["ev1"]}],
        "locators": [{"evidence_id": "ev1", "section_path": ["Experiments"], "sentence_id": "s1", "page": 5,
                      "bboxes": [{"page": 5, "x": 10, "y": 20, "width": 100, "height": 12}]}],
    }
    (gold_dir / "p1.json").write_text(json.dumps({**base, "review_status": "verified"}), encoding="utf-8")
    (gold_dir / "p2.json").write_text(json.dumps({**base, "paper_id": "p2", "review_status": "unreviewed"}), encoding="utf-8")
    prediction = {**base, "review_status": "silver"}
    prediction["numeric_results"] = [{**base["numeric_results"][0], "value": "83.2"}]
    (prediction_dir / "p1.json").write_text(json.dumps(prediction), encoding="utf-8")
    (prediction_dir / "MANIFEST.json").write_text(json.dumps({"immutable": True}), encoding="utf-8")
    result = evaluate_gold_corpus(gold_dir, prediction_dir)
    assert result.evaluated_papers == 1
    assert result.skipped_unverified_papers == 1
    assert result.entity.f1 == 1
    assert result.relation.f1 == 1
    assert result.claim.f1 == 1
    assert result.claim_exact.f1 == 1
    assert result.numeric_result.f1 == 1
    assert result.locator_exact_accuracy == 1
    assert result.locator_bbox_accuracy == 1
    loaded_gold = load_gold_directory(gold_dir)[0]
    loaded_prediction = load_gold_directory(prediction_dir)[0]
    per_paper = evaluate_paper(loaded_gold, loaded_prediction)
    assert per_paper.entity.f1 == 1
    assert per_paper.claim_exact.f1 == 1
    assert per_paper.locator_exact_accuracy == 1

    ai_reference = {**base, "review_status": "ai_verified"}
    (gold_dir / "p1.json").write_text(json.dumps(ai_reference), encoding="utf-8")
    with pytest.raises(ValueError, match="review_status"):
        evaluate_gold_corpus(gold_dir, prediction_dir)
    ai_result = evaluate_gold_corpus(
        gold_dir,
        prediction_dir,
        accepted_statuses={GoldReviewStatus.ai_verified},
    )
    assert ai_result.evaluated_papers == 1
    assert ai_result.entity.f1 == 1


def test_formal_eval_refuses_unreviewed_templates(tmp_path):
    gold = tmp_path / "gold"
    pred = tmp_path / "pred"
    gold.mkdir()
    pred.mkdir()
    template = {
        "paper_id": "p", "title": "P", "venue": "ICLR", "year": 2024, "pdf_path": "p.pdf",
        "review_status": "unreviewed",
    }
    (gold / "p.json").write_text(json.dumps(template), encoding="utf-8")
    with pytest.raises(ValueError, match="verified"):
        evaluate_gold_corpus(gold, pred)
