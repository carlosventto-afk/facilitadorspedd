"""operator company link (vinculo operador-empresa)

Revision ID: 0006
Revises: 0005
Create Date: 2026-07-24 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "operator_company_links",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "user_id", sa.String(36),
            sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column(
            "company_id", sa.String(36),
            sa.ForeignKey("companies.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("user_id", "company_id", name="uq_operator_company"),
    )
    op.create_index("ix_operator_company_links_user_id", "operator_company_links", ["user_id"])
    op.create_index(
        "ix_operator_company_links_company_id", "operator_company_links", ["company_id"]
    )


def downgrade() -> None:
    op.drop_table("operator_company_links")
