"""company cnpj registry data

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-17 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("companies", sa.Column("nome_fantasia", sa.String(255)))
    op.add_column("companies", sa.Column("situacao_cadastral", sa.String(50)))
    op.add_column("companies", sa.Column("data_abertura", sa.Date))
    op.add_column("companies", sa.Column("natureza_juridica", sa.String(255)))
    op.add_column("companies", sa.Column("porte", sa.String(50)))
    op.add_column("companies", sa.Column("cnae_principal", sa.String(20)))
    op.add_column("companies", sa.Column("cnae_descricao", sa.String(255)))
    op.add_column("companies", sa.Column("telefone", sa.String(20)))
    op.add_column("companies", sa.Column("email", sa.String(255)))
    op.add_column("companies", sa.Column("cep", sa.String(10)))
    op.add_column("companies", sa.Column("logradouro", sa.String(255)))
    op.add_column("companies", sa.Column("numero", sa.String(20)))
    op.add_column("companies", sa.Column("complemento", sa.String(100)))
    op.add_column("companies", sa.Column("bairro", sa.String(100)))
    op.add_column("companies", sa.Column("municipio", sa.String(100)))


def downgrade() -> None:
    op.drop_column("companies", "municipio")
    op.drop_column("companies", "bairro")
    op.drop_column("companies", "complemento")
    op.drop_column("companies", "numero")
    op.drop_column("companies", "logradouro")
    op.drop_column("companies", "cep")
    op.drop_column("companies", "email")
    op.drop_column("companies", "telefone")
    op.drop_column("companies", "cnae_descricao")
    op.drop_column("companies", "cnae_principal")
    op.drop_column("companies", "porte")
    op.drop_column("companies", "natureza_juridica")
    op.drop_column("companies", "data_abertura")
    op.drop_column("companies", "situacao_cadastral")
    op.drop_column("companies", "nome_fantasia")
