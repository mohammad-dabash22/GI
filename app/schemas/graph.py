from typing import Any
from pydantic import BaseModel, Field


class ProjectIdRequest(BaseModel):
    project_id: int


class CreateNodeRequest(BaseModel):
    project_id: int
    name: str = Field(..., min_length=1)
    type: str = "Person"
    properties: dict[str, Any] = {}


class DeleteNodeRequest(BaseModel):
    project_id: int
    node_id: str


class CreateConnectionRequest(BaseModel):
    project_id: int
    from_id: str
    to_id: str
    type: str = "related_to"
    label: str = ""


class DeleteConnectionRequest(BaseModel):
    project_id: int
    edge_id: str


class MergeNodesRequest(BaseModel):
    project_id: int
    target_id: str
    source_id: str


class UpdateEntityRequest(BaseModel):
    project_id: int
    entity_id: str
    fields: dict[str, Any] = {}


class UpdateEdgeRequest(BaseModel):
    project_id: int
    edge_index: int | None = None
    edge_id: str = ""
    fields: dict[str, Any] = {}


class UpdateEvidenceLegacyRequest(BaseModel):
    project_id: int
    entity_id: str = ""
    evidence: str = ""


class UpdateEdgeEvidenceLegacyRequest(BaseModel):
    project_id: int
    edge_index: int | None = None
    edge_id: str = ""
    evidence: str = ""


class ChatRequest(BaseModel):
    project_id: int
    question: str


class FindPathRequest(BaseModel):
    project_id: int
    from_id: str
    to_id: str
    max_depth: int = 10


class FindAllPathsRequest(BaseModel):
    project_id: int
    from_id: str
    to_id: str
    max_depth: int = 5


class ReviewActionRequest(BaseModel):
    project_id: int
    id: str


class ReviewRestoreRequest(BaseModel):
    project_id: int
    index: int
