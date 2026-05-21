import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.models import Base, JSON_VARIANT


class TeacherJob(Base):
    __tablename__ = "teacher_jobs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    status = Column(String, nullable=False, default="pending")
    openrouter_model = Column(String, nullable=False)
    # Snapshot of the sample-list filter the admin used so the job is auditable later.
    filter_json = Column(JSON_VARIANT, nullable=True)
    total = Column(Integer, nullable=False, default=0)
    processed = Column(Integer, nullable=False, default=0)
    succeeded = Column(Integer, nullable=False, default=0)
    failed = Column(Integer, nullable=False, default=0)
    last_error = Column(String, nullable=True)
    # Real billed cost from OpenRouter, summed across all processed items. Estimated total
    # cost is derived on the fly as cost_usd / processed * total — no need to store it.
    cost_usd = Column(Float, nullable=False, default=0.0)
    tokens_input = Column(BigInteger, nullable=False, default=0)
    tokens_output = Column(BigInteger, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)

    owner = relationship("User")
    items = relationship(
        "TeacherJobItem",
        back_populates="job",
        cascade="all, delete-orphan",
        order_by="TeacherJobItem.created_at",
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'running', 'done', 'cancelled')",
            name="ck_teacher_jobs_status",
        ),
        Index("ix_teacher_jobs_owner_id", "owner_id"),
        Index("ix_teacher_jobs_status", "status"),
    )


class TeacherJobItem(Base):
    __tablename__ = "teacher_job_items"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id = Column(UUID(as_uuid=True), ForeignKey("teacher_jobs.id", ondelete="CASCADE"), nullable=False)
    sample_id = Column(UUID(as_uuid=True), ForeignKey("samples.id", ondelete="CASCADE"), nullable=False)
    status = Column(String, nullable=False, default="queued")
    error_message = Column(String, nullable=True)
    detection_count = Column(Integer, nullable=True)
    detection_score = Column(String, nullable=True)
    cost_usd = Column(Float, nullable=True)
    tokens_input = Column(Integer, nullable=True)
    tokens_output = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    processed_at = Column(DateTime(timezone=True), nullable=True)

    job = relationship("TeacherJob", back_populates="items")
    sample = relationship("Sample")

    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'done', 'error', 'skipped')",
            name="ck_teacher_job_items_status",
        ),
        Index("ix_teacher_job_items_job_id_status", "job_id", "status"),
        Index("ix_teacher_job_items_status", "status"),
    )
