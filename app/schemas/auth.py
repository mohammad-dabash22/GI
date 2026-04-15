from pydantic import BaseModel, Field


class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=2, description="Must be at least 2 characters")
    password: str = Field(..., min_length=4, description="Must be at least 4 characters")


class LoginRequest(BaseModel):
    username: str
    password: str
