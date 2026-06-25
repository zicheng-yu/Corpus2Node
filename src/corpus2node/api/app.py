from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from corpus2node import __version__
from corpus2node.api.routes import chat as chat_routes
from corpus2node.api.routes import exam as exam_routes
from corpus2node.api.routes import export as export_routes
from corpus2node.api.routes import graph as graph_routes
from corpus2node.api.routes import notes as notes_routes
from corpus2node.api.routes import prompts as prompts_routes
from corpus2node.api.routes import sessions as sessions_routes
from corpus2node.api.routes import settings as settings_routes
from corpus2node.api.routes import workflow as workflow_routes
from corpus2node.config import ROOT_DIR, settings
from corpus2node.core.logging_config import configure_logging

configure_logging()
logger = logging.getLogger("corpus2node.api")

app = FastAPI(title="Corpus2Node API", version=__version__)


def _cors_origins() -> list[str]:
    configured = [origin.strip() for origin in settings.cors_allow_origins.split(",") if origin.strip()]
    return configured or ["*"]


_PUBLIC_PATH_PREFIXES = ("/health", "/ui", "/docs", "/redoc", "/openapi.json")

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def optional_bearer_auth(request: Request, call_next):
    """Protect the API when API_AUTH_TOKEN is configured; keep local dev zero-config."""
    token = settings.api_auth_token
    if (
        token
        and request.method != "OPTIONS"
        and not request.url.path.startswith(_PUBLIC_PATH_PREFIXES)
        and request.headers.get("authorization") != f"Bearer {token}"
    ):
        return JSONResponse(status_code=401, content={"detail": "Unauthorized"})
    return await call_next(request)


@app.exception_handler(Exception)
async def on_unhandled_error(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    include_traceback = settings.debug_tracebacks and settings.app_env.lower() != "production"
    content = {"detail": str(exc) if include_traceback else "Internal server error.", "type": type(exc).__name__}
    if include_traceback:
        import traceback

        content["traceback"] = traceback.format_exc()
    return JSONResponse(
        status_code=500,
        content=content,
    )


app.include_router(sessions_routes.router)
app.include_router(settings_routes.router)
app.include_router(prompts_routes.router)
app.include_router(workflow_routes.router)
app.include_router(graph_routes.router)
app.include_router(chat_routes.router)
app.include_router(notes_routes.router)
app.include_router(exam_routes.router)
app.include_router(export_routes.router)


@app.get("/health")
async def health() -> dict[str, object]:
    return {
        "status": "ok",
        "service": "corpus2node",
        "version": __version__,
        "storage_path": settings.local_storage_path,
        "vector_store_provider": settings.vector_store_provider,
    }


# Minimal no-build verification UI (served at /ui/); the main frontend lives in frontend/.
_WEB_DIR = ROOT_DIR / "web"
if _WEB_DIR.is_dir():
    app.mount("/ui", StaticFiles(directory=str(_WEB_DIR), html=True), name="ui")
