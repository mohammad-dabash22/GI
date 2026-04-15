from pydantic import BaseModel, Field


class CreateProjectRequest(BaseModel):
    name: str = Field(..., min_length=1)
    description: str = ""


class ProjectIdRequest(BaseModel):
    project_id: int


class SavePositionsRequest(BaseModel):
    project_id: int
    positions: dict
