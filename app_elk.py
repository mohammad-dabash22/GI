"""ELK layout branch launcher -- imports main app, runs on port 8053."""
from app import app
import uvicorn

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8053)
