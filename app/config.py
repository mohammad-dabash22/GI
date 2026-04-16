"""Infrastructure configuration loaded from environment variables.

Domain constants (entity types, relationship types, document types) live in
app/domain/ — this module holds only infrastructure and operational settings.
"""

import os
import secrets

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ── File storage ─────────────────────────────────────────────────────────────

UPLOAD_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "uploads")
ALLOWED_EXTENSIONS = {".pdf", ".docx", ".doc", ".txt", ".md", ".xlsx", ".csv"}

# ── Security ─────────────────────────────────────────────────────────────────

SECRET_KEY = os.environ.get("SECRET_KEY", secrets.token_hex(32))
JWT_EXPIRY_HOURS = int(os.environ.get("JWT_EXPIRY_HOURS", "24"))

# ── Database ─────────────────────────────────────────────────────────────────

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./forensic_graph.db")

# ── Azure OpenAI ─────────────────────────────────────────────────────────────

AZURE_OPENAI_ENDPOINT = os.environ.get("AZURE_OPENAI_ENDPOINT", "")
AZURE_OPENAI_KEY = os.environ.get("AZURE_OPENAI_KEY", "")
AZURE_OPENAI_API_VERSION = os.environ.get("AZURE_OPENAI_API_VERSION", "2024-12-01-preview")
AZURE_OPENAI_DEPLOYMENT = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-4o-mini")

# Models (all map to the same deployment by default; override per-env if needed)
FAST_MODEL = AZURE_OPENAI_DEPLOYMENT
STRONG_MODEL = AZURE_OPENAI_DEPLOYMENT
FALLBACK_MODEL = AZURE_OPENAI_DEPLOYMENT

# ── Operational tuning ───────────────────────────────────────────────────────

MAX_CONCURRENT_CALLS = 5
DEDUP_STRING_THRESHOLD = 0.70
DEDUP_EMBEDDING_THRESHOLD = 0.85
