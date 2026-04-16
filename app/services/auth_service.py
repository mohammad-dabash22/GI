"""Authentication service: password hashing, JWT token management, FastAPI dependencies."""

from datetime import datetime, timedelta, timezone
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import bcrypt
import jwt

from app.config import SECRET_KEY, JWT_EXPIRY_HOURS

_bearer = HTTPBearer(auto_error=False)


def hash_password(plain: str) -> str:
    """Hash a plaintext password with bcrypt."""
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    """Verify a plaintext password against a bcrypt hash."""
    return bcrypt.checkpw(plain.encode(), hashed.encode())


def create_token(user_id: int, username: str) -> str:
    """Create a JWT token for an authenticated user."""
    payload = {
        "sub": str(user_id),
        "username": username,
        "exp": datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRY_HOURS),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm="HS256")


def decode_token(token: str) -> dict:
    """Decode and validate a JWT token."""
    try:
        data = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
        data["sub"] = int(data["sub"])
        return data
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")


def get_current_user(creds: HTTPAuthorizationCredentials = Depends(_bearer)) -> dict:
    """FastAPI dependency: extract and validate the current user from JWT."""
    if creds is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    return decode_token(creds.credentials)


def get_current_user_or_token(creds: HTTPAuthorizationCredentials = Depends(_bearer),
                              token: str = None) -> dict:
    """FastAPI dependency: accept JWT from header or query param (for report export)."""
    if creds is not None:
        return decode_token(creds.credentials)
    if token:
        return decode_token(token)
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
