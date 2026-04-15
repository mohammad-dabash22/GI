"""Application entrypoint. Run with: uvicorn main:app --reload"""
from app.main import app  # noqa: F401

if __name__ == "__main__":
    import os
    import uvicorn
    port = int(os.environ.get("PORT", "8050"))
    uvicorn.run(app, host="0.0.0.0", port=port)
