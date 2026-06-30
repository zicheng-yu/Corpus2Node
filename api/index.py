from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

# Vercel functions do not provide a durable project filesystem. This preview
# deployment stores temporary debug artifacts in the writable runtime temp dir.
os.environ.setdefault("APP_ENV", "production")
os.environ.setdefault("DEBUG_TRACEBACKS", "false")
os.environ.setdefault("LOCAL_STORAGE_PATH", "/tmp/corpus2node-artifacts")
os.environ.setdefault("VECTOR_STORE_PATH", "/tmp/corpus2node-artifacts/indexes")
os.environ.setdefault("EMBED_PROVIDER", "hashing")
os.environ.setdefault("EMBEDDING_DIMENSIONS", "1024")
os.environ.setdefault("VECTOR_STORE_PROVIDER", "local_cosine")
os.environ.setdefault("GRAPH_CRITIC_ENABLED", "false")
os.environ.setdefault("MAX_UPLOAD_BYTES", str(50 * 1024 * 1024))

from corpus2node.api.app import app  # noqa: E402,F401
