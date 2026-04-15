"""Audit log service: chain-of-custody tracking for forensic compliance."""

import json
import os
from datetime import datetime, timezone

LOG_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "audit_log.jsonl")

_log_entries = []


def _ts():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def log_action(action: str, user: str = "investigator", details: dict = None):
    """Record an auditable action to both memory and persistent JSONL file."""
    entry = {
        "timestamp": _ts(),
        "action": action,
        "user": user,
        "details": details or {},
    }
    _log_entries.append(entry)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass


def get_log(limit: int = 200, offset: int = 0) -> list[dict]:
    """Retrieve recent audit log entries (newest first)."""
    if _log_entries:
        entries = list(reversed(_log_entries))
        return entries[offset : offset + limit]
    # Fallback: read from file
    try:
        with open(LOG_FILE, "r", encoding="utf-8") as f:
            lines = f.readlines()
        entries = [json.loads(line) for line in reversed(lines) if line.strip()]
        return entries[offset : offset + limit]
    except Exception:
        return []


def clear_log():
    """Clear all audit log entries (for testing)."""
    global _log_entries
    _log_entries = []
    try:
        open(LOG_FILE, "w").close()
    except Exception:
        pass
