"""Backward-compatibility shim. The application now lives in main.py.

Kept so that any tooling referencing `app:app` still works.
Prefer using `uvicorn main:app` going forward.
"""
from main import app  # noqa: F401

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8050)
