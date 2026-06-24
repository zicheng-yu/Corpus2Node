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

    # --- Kimi (PDF extraction via Files API; NOT a LangChain chat model) ---
    kimi_base_url: str = "https://api.moonshot.cn/v1"
    kimi_api_key: str = ""
    kimi_model: str = "kimi-k2.6"
    kimi_timeout_seconds: float = 60.0

    # --- Embeddings ---
    embed_provider: str = "bge_m3"  # bge_m3 | openai_compatible
    embedding_base_url: str = ""
    embedding_api_key: str = ""
    embedding_model: str = ""
    embedding_dimensions: int = 1024
    embedding_batch_size: int = 32
    embedding_timeout_seconds: float = 30.0
    embedding_local_model_name: str = "BAAI/bge-m3"
    embedding_local_device: str = "cpu"
    embedding_local_use_fp16: bool = False

    # --- Audio transcription (Whisper / faster-whisper) ---
    whisper_model_size: str = "base"
    whisper_language: str = "auto"
    faster_whisper_python_path: str = ""
    faster_whisper_runner_path: str = ""

    # --- Observability ---
    langchain_tracing: bool = False
    langsmith_api_key: str = ""

    # --- PDF export ---
    wkhtmltopdf_path: str = ""


settings = Settings()
