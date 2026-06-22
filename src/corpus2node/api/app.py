from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from corpus2node import __version__
from corpus2node.api.routes import chat as chat_routes
from corpus2node.api.routes import settings as settings_routes
from corpus2node.api.routes import workflow as workflow_routes
from corpus2node.config import settings

app = FastAPI(title="Corpus2Node API", version=__version__)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

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
