#!/usr/bin/env python3
from __future__ import annotations

import argparse

from corpus2node.scientific.evaluation import evaluate_gold_corpus


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate verified scientific gold annotations.")
    parser.add_argument("gold_dir")
    parser.add_argument("prediction_dir")
    parser.add_argument("--allow-unreviewed", action="store_true")
    args = parser.parse_args()
    result = evaluate_gold_corpus(
        args.gold_dir,
        args.prediction_dir,
        require_verified=not args.allow_unreviewed,
    )
    print(result.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
