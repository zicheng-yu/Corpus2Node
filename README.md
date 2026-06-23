# Corpus2Node

Turn any corpus of material — course slides, project docs, onboarding material,
meeting recordings — into an **explorable, citable knowledge graph**. New people
build a mental map fast, and every answer traces back to a graph node and the
source chunk it came from.

> **资料图数据库化 + 解释性**：不是黑箱 RAG——你能看见概念、关系，并把每个回答溯源到具体的图节点和原文。

## Architecture (one line)

An offline **LangGraph workflow** turns raw material into a knowledge graph (with
an LLM-judge quality gate); an online **LangChain agent** answers questions,
quizzes, and drafts notes by retrieving over that graph — deterministic graph
algorithms are kept out of the LLM's hands.

> Working notes, the full refactor plan, and the donor-repo copy map live in
> [`CLAUDE.md`](./CLAUDE.md).

## Quickstart (dev)

```bash
uv sync                                  # create env + install (Python 3.12)
uv run uvicorn corpus2node.api.app:app --reload
curl localhost:8000/health
uv run pytest -q
```

Heavy ingest/embedding deps install on demand:

```bash
uv sync --extra ml
```

## Status

Greenfield rebuild of the former `Course2Node` course project. Step 0 (scaffold)
is in place; see `CLAUDE.md` §9 for the startup sequence.
