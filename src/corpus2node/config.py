from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# src/corpus2node/config.py -> parents[2] == repo root
ROOT_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Infrastructure settings only.

    Chat/LLM credentials are intentionally NOT here — they live in a runtime,
    multi-credential registry (see ``corpus2node.llm.store`` / ``.credentials``)
    so users can stash multiple keys (OpenAI-compatible and Anthropic) and bind
    each purpose (graph/critic/chat/exam) to one. The env vars below are only a
    first-run convenience seed for that registry.
    """

    model_config = SettingsConfigDict(env_file=str(ROOT_DIR / ".env"), extra="ignore")

    # --- Storage (local JSON artifacts are the source of truth) ---
    local_storage_path: str = str(ROOT_DIR / "artifacts")

    # --- API safety ---
    app_env: str = "development"  # development | production
    debug_tracebacks: bool = True
    cors_allow_origins: str = "*"  # comma-separated origins; "*" is dev only
    api_auth_token: str = ""  # optional in development; required by default in production
    require_auth_in_production: bool = True
    allow_ephemeral_storage: bool = False
    max_upload_bytes: int = 500 * 1024 * 1024
    max_document_upload_bytes: int = 50 * 1024 * 1024
    max_pdf_upload_bytes: int = 200 * 1024 * 1024
    max_image_upload_bytes: int = 20 * 1024 * 1024
    max_archive_uncompressed_bytes: int = 200 * 1024 * 1024
    upload_chunk_size: int = 1024 * 1024

    # --- Vector index (online retrieval) ---
    vector_store_provider: str = "local_cosine"  # local_cosine | chroma
    vector_store_path: str = str(ROOT_DIR / "artifacts" / "indexes")

    # --- Graph extraction (batching + concurrency; not credentials) ---
    extract_batch_max_chars: int = 5200
    extract_batch_max_chunks: int = 8
    extract_max_concurrency: int = 8

    # --- Graph critic (LLM-judge quality gate; costs an extra pass — disable to save tokens) ---
    graph_critic_enabled: bool = True
    critic_batch_concepts: int = 40
    critic_batch_relations: int = 60

    # --- Multimodal ingestion (Kimi image/PDF/video) ---
    # Credentials are NOT here — bind a credential to the `vision` purpose in the
    # registry (Settings → Models). This is just the request timeout (infra).
    vision_timeout_seconds: float = 120.0

    # --- Scientific PDF structure parsing (GROBID REST service) ---
    grobid_base_url: str = "http://localhost:8070"

    # --- Embeddings ---
    # embed_provider picks the engine. For `openai_compatible`, the endpoint/key/model
    # come from the registry's `embedding` purpose (Settings → Models), not from here.
    embed_provider: str = "bge_m3"  # bge_m3 | openai_compatible | hashing
    embedding_dimensions: int = 1024
    embedding_batch_size: int = 32
    embedding_timeout_seconds: float = 30.0
    embedding_local_model_name: str = "BAAI/bge-m3"
    embedding_local_use_fp16: bool = False

    # --- Audio transcription (Whisper / faster-whisper) ---
    whisper_model_size: str = "base"
    whisper_language: str = "auto"

    # --- Observability ---
    langchain_tracing: bool = False
    langsmith_api_key: str = ""

    # --- PDF export ---
    wkhtmltopdf_path: str = ""


settings = Settings()
