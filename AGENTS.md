# AGENTS.md

> Note: the active product code lives on the **`feat`** branch. `main` is an empty scaffold.

## Cursor Cloud specific instructions

Corpus2Node is a two-process app: a **FastAPI backend** (Python 3.12, managed by `uv`) plus a
**React/Vite frontend**. Storage is local JSON under `artifacts/` — there is no database, Redis, or
worker process. Standard dev/verify commands are documented in `docs/PROGRESS.md` (标准启动路径 /
标准验证路径), the `scripts/corpus.sh` header, and `.github/workflows/ci.yml`. Notes below only cover
non-obvious caveats.

### Environment already provisioned (by the startup update script)
- `uv` is installed at `~/.local/bin` (on `PATH` via `~/.bashrc`) and backend deps are synced with
  `uv sync --dev`. Frontend deps are installed with `npm ci` in `frontend/`.
- The optional extras `ml` (BGE-M3 + torch) and `export` (pdf) are **not** installed — they are heavy
  and not needed for tests, lint, build, or the offline dev flow.

### Running the services (do NOT put these in the update script)
- Both: `scripts/corpus.sh dev` (foreground) or `scripts/corpus.sh start` (background, logs in
  `.run/logs/`). Backend alone: `uv run uvicorn corpus2node.api.app:app --reload --port 8000`.
  Frontend alone: `cd frontend && npm run dev -- --port 5173`.
- Backend serves `/health`, `/docs`, and a zero-build fallback UI at `/ui`. The Vite dev server on
  `:5173` proxies `/api` → `:8000`.

### Non-obvious caveats
- **Embeddings default to `bge_m3`, which requires the un-installed `ml` extra.** To run/index without
  torch, set `EMBED_PROVIDER=hashing` in a local `.env` (gitignored; copy from `.env.example`). This
  repo's dev `.env` uses `hashing`. Without it, any ingestion/search would try to load BGE-M3 and fail.
- **LLM credentials are configured in the UI (设置 → 模型), not `.env`** — they persist to
  `artifacts/llm_settings.json`. With no credentials bound, session creation + file upload work, but
  the graph pipeline (ingest→extract→critic→build) and chat/notes/exam **fail at the LLM extract
  step**. This is expected without user API keys, not an environment bug. Full AI E2E needs
  user-provided keys (OpenAI-compatible / Anthropic; Kimi for PDF/image/video ingest).
- `artifacts/`, `.env*`, `AGENTS.md`, and `CLAUDE.md` are gitignored. `docs/PROGRESS.md` is the
  canonical, up-to-date progress/architecture map (in Chinese) — read it first.
- Tests run fully offline (LLM paths are mocked/seamed); `uv run pytest -q` is authoritative and uses
  the same ASGI app as uvicorn.
