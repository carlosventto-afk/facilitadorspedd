"""pending antecipacao credit (E111 timing)

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-21 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "pending_antecipacao_credits",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "company_id", sa.String(36),
            sa.ForeignKey("companies.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("competencia_origem", sa.Date, nullable=False),
        sa.Column("valor", sa.Numeric(15, 2), nullable=False),
        sa.Column(
            "status", sa.Enum("PENDING", "CLAIMED", name="creditstatus"),
            nullable=False, server_default="PENDING",
        ),
        sa.Column(
            "source_job_id", sa.String(36),
            sa.ForeignKey("processing_jobs.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column(
            "claimed_in_job_id", sa.String(36),
            sa.ForeignKey("processing_jobs.id", ondelete="SET NULL"), nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("company_id", "competencia_origem", name="uq_company_competencia_origem"),
    )
    op.create_index(
        "ix_pending_antecipacao_credits_company_id",
        "pending_antecipacao_credits", ["company_id"],
    )


def downgrade() -> None:
    op.drop_table("pending_antecipacao_credits")
