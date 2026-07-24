"""invitation (convite de gestor por e-mail)

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-23 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "invitations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column(
            "accounting_firm_id", sa.String(36),
            sa.ForeignKey("accounting_firms.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column(
            "status", sa.Enum("PENDING", "ACCEPTED", "CANCELED", name="invitationstatus"),
            nullable=False, server_default="PENDING",
        ),
        sa.Column(
            "invited_by", sa.String(36),
            sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
        ),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_user_id", sa.String(36),
            sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_invitations_email", "invitations", ["email"])
    op.create_index("ix_invitations_accounting_firm_id", "invitations", ["accounting_firm_id"])


def downgrade() -> None:
    op.drop_table("invitations")
