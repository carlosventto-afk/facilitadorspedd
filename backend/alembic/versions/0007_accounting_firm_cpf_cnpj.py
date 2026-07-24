"""accounting_firm cpf_cnpj (permite cadastro por CPF, além de CNPJ)

Revision ID: 0007
Revises: 0006
Create Date: 2026-07-24 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column("accounting_firms", "cnpj", new_column_name="cpf_cnpj")


def downgrade() -> None:
    op.alter_column("accounting_firms", "cpf_cnpj", new_column_name="cnpj")
