from pydantic import BaseModel, Field


class CreateProjectRequest(BaseModel):
    name: str = Field(..., min_length=1)
    description: str = ""


class SavePositionsRequest(BaseModel):
    project_id: int
    positions: dict
