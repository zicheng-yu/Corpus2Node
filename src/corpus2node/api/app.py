from __future__ import annotations

import hmac
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from corpus2node import __version__
from corpus2node.accounts.database import dispose_db, init_db, session_factory
from corpus2node.accounts.service import resolve_principal, validate_csrf
from corpus2node.api.routes import admin as admin_routes
from corpus2node.api.routes import auth as auth_routes
from corpus2node.api.routes import chat as chat_routes
from corpus2node.api.routes import discovery as discovery_routes
from corpus2node.api.routes import exam as exam_routes
from corpus2node.api.routes import export as export_routes
from corpus2node.api.routes import graph as graph_routes
from corpus2node.api.routes import notes as notes_routes
from corpus2node.api.routes import organizations as organizations_routes
from corpus2node.api.routes import projects as projects_routes
from corpus2node.api.routes import prompts as prompts_routes
from corpus2node.api.routes import sessions as sessions_routes
from corpus2node.api.routes import scientific as scientific_routes
from corpus2node.api.routes import shares as shares_routes
from corpus2node.api.routes import settings as settings_routes
from corpus2node.api.routes import workflow as workflow_routes
from corpus2node.config import ROOT_DIR, settings
from corpus2node.core.logging_config import configure_logging

configure_logging()
logger = logging.getLogger("corpus2node.api")

_IS_PRODUCTION = settings.app_env.lower() == "production"


@asynccontextmanager
async def lifespan(_: FastAPI):
    if settings.auth_mode == "accounts":
        await init_db()
    yield
    await dispose_db()


app = FastAPI(
    title="Corpus2Node API",
    version=__version__,
    docs_url=None if _IS_PRODUCTION else "/docs",
    redoc_url=None if _IS_PRODUCTION else "/redoc",
    openapi_url=None if _IS_PRODUCTION else "/openapi.json",
    lifespan=lifespan,
)


def _cors_origins() -> list[str]:
    configured = [origin.strip() for origin in settings.cors_allow_origins.split(",") if origin.strip()]
    if settings.app_env.lower() == "production":
        return [origin for origin in configured if origin != "*"]
    return [origin for origin in configured if origin != "*"]


def _cors_origin_regex() -> str | None:
    configured = {origin.strip() for origin in settings.cors_allow_origins.split(",") if origin.strip()}
    return r"https?://.*" if "*" in configured and not _IS_PRODUCTION else None


_PUBLIC_PATHS = frozenset({"/health", "/ui", "/ui/", "/auth/login", "/auth/activate", "/public/shares/resolve"})


def _canonical_path(path: str) -> str:
    return path[4:] if path.startswith("/api/") else path


def _is_public_path(path: str) -> bool:
    path = _canonical_path(path)
    return path in _PUBLIC_PATHS or path.startswith("/ui/")

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_origin_regex=_cors_origin_regex(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def authentication(request: Request, call_next):
    """Legacy shared token or tenant-aware account sessions, selected explicitly."""
    mode = settings.auth_mode
    if mode not in {"disabled", "legacy_token", "accounts"}:
        return JSONResponse(status_code=503, content={"detail": "Invalid AUTH_MODE configuration."})
    if mode == "disabled":
        return await call_next(request)

    token = settings.api_auth_token
    protected = (
        request.method != "OPTIONS"
        and not _is_public_path(request.url.path)
    )
    if mode == "accounts":
        if settings.app_env.lower() == "production" and settings.database_url.startswith("sqlite"):
            return JSONResponse(status_code=503, content={"detail": "Accounts mode requires PostgreSQL in production."})
        await init_db()
        if not protected:
            return await call_next(request)
        session_token = request.cookies.get("c2n_session", "")
        if not session_token:
            return JSONResponse(status_code=401, content={"detail": "Authentication required."})
        async with session_factory()() as db:
            principal = await resolve_principal(db, session_token, request.headers.get("x-organization-id"))
            if principal is None:
                return JSONResponse(status_code=401, content={"detail": "Invalid or expired session."})
            if request.method not in {"GET", "HEAD", "OPTIONS"}:
                csrf = request.headers.get("x-csrf-token", "")
                if not await validate_csrf(db, session_token, csrf):
                    return JSONResponse(status_code=403, content={"detail": "CSRF validation failed."})
                origin = request.headers.get("origin")
                if not origin or origin.rstrip("/") not in _allowed_account_origins():
                    return JSONResponse(status_code=403, content={"detail": "Origin is not allowed."})
            request.state.principal = principal
            await db.commit()
        return await call_next(request)

    # legacy_token mode preserves the previous deployment contract.
    if (
        protected
        and settings.app_env.lower() == "production"
        and settings.require_auth_in_production
        and not token
    ):
        return JSONResponse(
            status_code=503,
            content={"detail": "API_AUTH_TOKEN must be configured in production."},
        )
    if (
        protected
        and settings.app_env.lower() == "production"
        and not settings.allow_ephemeral_storage
        and Path(settings.local_storage_path).is_relative_to("/tmp")
    ):
        return JSONResponse(
            status_code=503,
            content={"detail": "Ephemeral /tmp storage is disabled for production."},
        )
    if (
        token
        and protected
        and not hmac.compare_digest(request.headers.get("authorization", ""), f"Bearer {token}")
    ):
        return JSONResponse(status_code=401, content={"detail": "Unauthorized"})
    return await call_next(request)


def _allowed_account_origins() -> set[str]:
    origins = {value.strip().rstrip("/") for value in settings.cors_allow_origins.split(",") if value.strip() != "*"}
    parsed = urlparse(settings.public_app_url)
    if parsed.scheme and parsed.netloc:
        origins.add(f"{parsed.scheme}://{parsed.netloc}")
    return origins


@app.exception_handler(Exception)
async def on_unhandled_error(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    include_traceback = settings.debug_tracebacks and settings.app_env.lower() != "production"
    content = {"detail": str(exc) if include_traceback else "Internal server error."}
    if include_traceback:
        content["type"] = type(exc).__name__
        import traceback

        content["traceback"] = traceback.format_exc()
    return JSONResponse(
        status_code=500,
        content=content,
    )


_ROUTERS = (
    auth_routes.router,
    organizations_routes.router,
    admin_routes.router,
    projects_routes.router,
    sessions_routes.router,
    settings_routes.router,
    prompts_routes.router,
    workflow_routes.router,
    graph_routes.router,
    chat_routes.router,
    discovery_routes.router,
    scientific_routes.router,
    shares_routes.router,
    notes_routes.router,
    exam_routes.router,
    export_routes.router,
)

for router in _ROUTERS:
    app.include_router(router)
    app.include_router(router, prefix="/api")


@app.get("/health")
@app.get("/api/health")
async def health() -> dict[str, object]:
    result: dict[str, object] = {
        "status": "ok",
        "service": "corpus2node",
        "version": __version__,
        "vector_store_provider": settings.vector_store_provider,
        "auth_configured": bool(settings.api_auth_token),
        "auth_mode": settings.auth_mode,
    }
    if settings.app_env.lower() != "production":
        result["storage_path"] = settings.local_storage_path
    return result


# Minimal no-build verification UI (served at /ui/); the main frontend lives in frontend/.
_WEB_DIR = ROOT_DIR / "web"
if _WEB_DIR.is_dir():
    app.mount("/ui", StaticFiles(directory=str(_WEB_DIR), html=True), name="ui")
