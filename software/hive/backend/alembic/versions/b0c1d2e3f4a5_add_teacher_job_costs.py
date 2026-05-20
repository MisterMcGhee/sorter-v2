"""add teacher job cost columns

Revision ID: b0c1d2e3f4a5
Revises: a9b0c1d2e3f4
Create Date: 2026-05-20 23:30:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b0c1d2e3f4a5"
down_revision: Union[str, None] = "a9b0c1d2e3f4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "teacher_jobs",
        sa.Column("cost_usd", sa.Float(), nullable=False, server_default="0"),
    )
    op.add_column(
        "teacher_jobs",
        sa.Column("tokens_input", sa.BigInteger(), nullable=False, server_default="0"),
    )
    op.add_column(
        "teacher_jobs",
        sa.Column("tokens_output", sa.BigInteger(), nullable=False, server_default="0"),
    )
    op.add_column("teacher_job_items", sa.Column("cost_usd", sa.Float(), nullable=True))
    op.add_column("teacher_job_items", sa.Column("tokens_input", sa.Integer(), nullable=True))
    op.add_column("teacher_job_items", sa.Column("tokens_output", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("teacher_job_items", "tokens_output")
    op.drop_column("teacher_job_items", "tokens_input")
    op.drop_column("teacher_job_items", "cost_usd")
    op.drop_column("teacher_jobs", "tokens_output")
    op.drop_column("teacher_jobs", "tokens_input")
    op.drop_column("teacher_jobs", "cost_usd")
