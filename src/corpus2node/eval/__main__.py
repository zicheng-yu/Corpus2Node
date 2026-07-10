"""CLI: run eval metrics for a session.

  python -m corpus2node.eval <session_id> --default-gold
  python -m corpus2node.eval <session_id> --gold path/to/gold.json --json out.json
  python -m corpus2node.eval <session_id> --qa "问题1" "问题2"      # QA grounding (needs LLM)
"""
from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
from uuid import UUID

from corpus2node.eval.harness import run_offline_report, run_qa_eval
from corpus2node.eval.schemas import EvalReport, default_gold, load_gold


def _print_report(report: EvalReport) -> None:
    print(f"\nEval · session {report.session_id}")
    if report.extraction:
        e = report.extraction
        print("\n[extraction]")
        print(f"  concepts      P={e.concept_precision}  R={e.concept_recall}  F1={e.concept_f1}  ({e.matched_gold}/{e.gold_concepts} gold, {e.predicted_concepts} predicted)")
        print(f"  relations     validity={e.relation_validity_rate}  recall={e.relation_recall}  ({e.edges} edges)")
    if report.notes:
        n = report.notes
        print("\n[notes]")
        print(f"  coverage={n.coverage}  ({n.covered}/{n.core_concepts} core concepts, {n.sections} sections)")
    if report.test:
        x = report.test
        print("\n[test]")
        print(f"  traceability={x.traceability}  ({x.traceable}/{x.questions})")
        print(f"  objective validity={x.objective_validity}  ({x.objective_valid}/{x.objective})")
    if report.qa:
        q = report.qa
        print("\n[qa]")
        print(f"  groundedness={q.groundedness}  chunk-grounded={q.chunk_grounded}/{q.questions}  avg citations={q.avg_citations}")
    print()


def main() -> None:
    parser = argparse.ArgumentParser(prog="corpus2node.eval", description="Run eval metrics for a session.")
    parser.add_argument("session_id", type=UUID)
    parser.add_argument("--gold", help="path to a gold dataset JSON (extraction eval)")
    parser.add_argument("--default-gold", action="store_true", help="use the packaged sample-lecture gold")
    parser.add_argument("--qa", nargs="*", metavar="Q", help="run QA grounding eval over these questions (needs LLM)")
    parser.add_argument("--json", help="also write the report JSON to this path")
    args = parser.parse_args()

    gold = load_gold(args.gold) if args.gold else (default_gold() if args.default_gold else None)
    report = run_offline_report(args.session_id, gold)
    if args.qa:
        report.qa = asyncio.run(run_qa_eval(args.session_id, args.qa))

    _print_report(report)
    if args.json:
        Path(args.json).write_text(report.model_dump_json(indent=2), encoding="utf-8")
        print(f"saved → {args.json}")


if __name__ == "__main__":
    main()
