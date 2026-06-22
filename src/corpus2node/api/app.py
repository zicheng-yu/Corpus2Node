from __future__ import annotations

import logging
import traceback

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from corpus2node import __version__
from corpus2node.api.routes import chat as chat_routes
from corpus2node.api.routes import sessions as sessions_routes
from corpus2node.api.routes import settings as settings_routes
from corpus2node.api.routes import workflow as workflow_routes
from corpus2node.config import ROOT_DIR, settings
from corpus2node.core.logging_config import configure_logging

configure_logging()
logger = logging.getLogger("corpus2node.api")

app = FastAPI(title="Corpus2Node API", version=__version__)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def on_unhandled_error(request: Request, exc: Exception) -> JSONResponse:
    # Log the full traceback (stays in the terminal) AND return it (stays on the page)
    # so errors can be copied/analysed during the manual-verification phase.
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": str(exc), "type": type(exc).__name__, "traceback": traceback.format_exc()},
    )


app.include_router(sessions_routes.router)
app.include_router(settings_routes.router)
app.include_router(workflow_routes.router)
app.include_router(chat_routes.router)


@app.get("/health")
async def health() -> dict[str, object]:
    return {
        "status": "ok",
        "service": "corpus2node",
        "version": __version__,
        "storage_path": settings.local_storage_path,
        "vector_store_provider": settings.vector_store_provider,
    }


# Minimal no-build verification UI (served at /ui/). Disposable — the real frontend
# will live under frontend/ and align with the original project's stack.
_WEB_DIR = ROOT_DIR / "web"
if _WEB_DIR.is_dir():
    app.mount("/ui", StaticFiles(directory=str(_WEB_DIR), html=True), name="ui")
