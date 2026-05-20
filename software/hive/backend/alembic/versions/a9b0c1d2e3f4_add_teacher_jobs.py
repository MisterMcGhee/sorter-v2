"""add teacher jobs

Revision ID: a9b0c1d2e3f4
Revises: f8b9c0d1e2f3
Create Date: 2026-05-20 22:30:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "a9b0c1d2e3f4"
down_revision: Union[str, None] = "f8b9c0d1e2f3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "teacher_jobs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("owner_id", sa.UUID(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("openrouter_model", sa.String(), nullable=False),
        sa.Column("filter_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("processed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("succeeded", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'done', 'cancelled')",
            name="ck_teacher_jobs_status",
        ),
    )
    op.create_index("ix_teacher_jobs_owner_id", "teacher_jobs", ["owner_id"], unique=False)
    op.create_index("ix_teacher_jobs_status", "teacher_jobs", ["status"], unique=False)

    op.create_table(
        "teacher_job_items",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("job_id", sa.UUID(), nullable=False),
        sa.Column("sample_id", sa.UUID(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="queued"),
        sa.Column("error_message", sa.String(), nullable=True),
        sa.Column("detection_count", sa.Integer(), nullable=True),
        sa.Column("detection_score", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["job_id"], ["teacher_jobs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["sample_id"], ["samples.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'done', 'error', 'skipped')",
            name="ck_teacher_job_items_status",
        ),
    )
    op.create_index(
        "ix_teacher_job_items_job_id_status",
        "teacher_job_items",
        ["job_id", "status"],
        unique=False,
    )
    op.create_index(
        "ix_teacher_job_items_status",
        "teacher_job_items",
        ["status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_teacher_job_items_status", table_name="teacher_job_items")
    op.drop_index("ix_teacher_job_items_job_id_status", table_name="teacher_job_items")
    op.drop_table("teacher_job_items")
    op.drop_index("ix_teacher_jobs_status", table_name="teacher_jobs")
    op.drop_index("ix_teacher_jobs_owner_id", table_name="teacher_jobs")
    op.drop_table("teacher_jobs")
