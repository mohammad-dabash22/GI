import os
import secrets

UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "uploads")
ALLOWED_EXTENSIONS = {".pdf", ".docx", ".doc", ".txt", ".md"}

SECRET_KEY = os.environ.get("SECRET_KEY", secrets.token_hex(32))
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./forensic_graph.db")
JWT_EXPIRY_HOURS = int(os.environ.get("JWT_EXPIRY_HOURS", "24"))

# Azure OpenAI
AZURE_OPENAI_ENDPOINT = os.environ.get(
    "AZURE_OPENAI_ENDPOINT",
    "https://ue2doai5kuaoa01.cognitiveservices.azure.com/",
)
AZURE_OPENAI_KEY = os.environ.get(
    "AZURE_OPENAI_KEY",
    "18c8b76fa6cf4972ab90203435b2ebfa",
)
AZURE_OPENAI_API_VERSION = os.environ.get(
    "AZURE_OPENAI_API_VERSION",
    "2024-12-01-preview",
)
AZURE_OPENAI_DEPLOYMENT = os.environ.get(
    "AZURE_OPENAI_DEPLOYMENT",
    "gpt-5.4-nano",
)

# Models
FAST_MODEL = AZURE_OPENAI_DEPLOYMENT
STRONG_MODEL = AZURE_OPENAI_DEPLOYMENT
FALLBACK_MODEL = AZURE_OPENAI_DEPLOYMENT

ENTITY_TYPES = [
    "Person", "Organization", "Account", "Phone", "Address",
    "Vehicle", "Email", "MoneyTransfer", "Document", "Event", "Location"
]

RELATIONSHIP_TYPES = [
    "owns", "works_for", "related_to", "transferred_money_to", "communicated_with",
    "located_at", "associated_with", "controls", "registered_to", "paid_by",
    "met_with", "traveled_to", "signed", "witnessed", "received_from",
    "shareholder_of", "board_member_of", "family", "referred_by", "financed",
    "sold_shares_to", "trades_with", "managed_by", "ceo_of", "director_of"
]

DOCUMENT_TYPES = [
    "Bank Statement",
    "Corporate Filing",
    "Investigation Report",
    "Interview Transcript",
    "Phone/Comms Records",
    "Legal Agreement",
    "Property Records",
    "Travel Records",
    "Other"
]

MAX_CONCURRENT_CALLS = 5
DEDUP_STRING_THRESHOLD = 0.70
DEDUP_EMBEDDING_THRESHOLD = 0.85
