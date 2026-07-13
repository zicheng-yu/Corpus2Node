"""Export the deterministic FastAPI OpenAPI document for contract drift checks."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from corpus2node.api.app import app


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="docs/openapi.json")
    args = parser.parse_args()
    target = Path(args.output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(app.openapi(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
