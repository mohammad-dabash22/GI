from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from sqlalchemy.orm import relationship

from app.models.base import Base


def _utcnow():
    return datetime.now(timezone.utc)


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
