from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from database import Base


def _utcnow():
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(100), unique=True, nullable=False, index=True)
    password_hash = Column(String(256), nullable=False)
    created_at = Column(DateTime, default=_utcnow)

    projects = relationship("Project", back_populates="creator")


class Project(Base):
    __tablename__ = "projects"

    id = Column(Integer, primary_key=True, index=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    name = Column(String(200), nullable=False)
    description = Column(Text, default="")
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)

    creator = relationship("User", back_populates="projects")
    snapshot = relationship("GraphSnapshot", back_populates="project", uselist=False)
    documents = relationship("DocumentRecord", back_populates="project")


class GraphSnapshot(Base):
    __tablename__ = "graph_snapshots"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), unique=True, nullable=False)
    entities = Column(Text, default="[]")
    relationships = Column(Text, default="[]")
    errors = Column(Text, default="[]")
    node_positions = Column(Text, default="{}")
    rejected_items = Column(Text, default="[]")
    saved_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)

    project = relationship("Project", back_populates="snapshot")


class DocumentRecord(Base):
    __tablename__ = "document_records"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    original_name = Column(String(300), nullable=False)
    stored_filename = Column(String(400), nullable=False)
    doc_type = Column(String(100), default="Other")
    file_path = Column(String(500), nullable=False)
    uploaded_at = Column(DateTime, default=_utcnow)

    project = relationship("Project", back_populates="documents")
