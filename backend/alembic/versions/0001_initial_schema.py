"""initial schema

Revision ID: 0001
Revises:
Create Date: 2025-01-01 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # subscriptions
    op.create_table(
        "subscriptions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "plan",
            sa.Enum("STARTER", "PROFESSIONAL", "ENTERPRISE", name="subscriptionplan"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum("TRIALING", "ACTIVE", "PAST_DUE", "CANCELED", name="subscriptionstatus"),
            nullable=False,
        ),
        sa.Column("stripe_subscription_id", sa.String(255)),
        sa.Column("stripe_customer_id", sa.String(255)),
        sa.Column("current_period_start", sa.DateTime(timezone=True)),
        sa.Column("current_period_end", sa.DateTime(timezone=True)),
        sa.Column("max_companies", sa.Integer, nullable=False, default=5),
        sa.Column("max_jobs_per_month", sa.Integer, nullable=False, default=20),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    # accounting_firms
    op.create_table(
        "accounting_firms",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("cnpj", sa.String(14), unique=True, nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("phone", sa.String(20)),
        sa.Column("subscription_id", sa.String(36), sa.ForeignKey("subscriptions.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    # users
    op.create_table(
        "users",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("email", sa.String(255), unique=True, nullable=False, index=True),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("full_name", sa.String(255), nullable=False),
        sa.Column(
            "role",
            sa.Enum("ADMIN", "GESTOR", "OPERADOR", name="userrole"),
            nullable=False,
        ),
        sa.Column("is_active", sa.Boolean, nullable=False, default=True),
        sa.Column("accounting_firm_id", sa.String(36), sa.ForeignKey("accounting_firms.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    # companies
    op.create_table(
        "companies",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("accounting_firm_id", sa.String(36), sa.ForeignKey("accounting_firms.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("cnpj", sa.String(14), nullable=False),
        sa.Column("inscricao_estadual", sa.String(50)),
        sa.Column("uf", sa.String(2), nullable=False, default="PA"),
        sa.Column("is_active", sa.Boolean, nullable=False, default=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("accounting_firm_id", "cnpj", name="uq_firm_company_cnpj"),
    )

    # processing_jobs
    op.create_table(
        "processing_jobs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("company_id", sa.String(36), sa.ForeignKey("companies.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_by", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=False),
        sa.Column(
            "status",
            sa.Enum("PENDING", "PROCESSING", "COMPLETED", "FAILED", name="jobstatus"),
            nullable=False,
            default="PENDING",
        ),
        sa.Column("period_start", sa.Date, nullable=False),
        sa.Column("period_end", sa.Date, nullable=False),
        sa.Column("sped_input_s3_key", sa.String(500)),
        sa.Column("excel_input_s3_key", sa.String(500)),
        sa.Column("sped_output_s3_key", sa.String(500)),
        sa.Column("nfs_found", sa.Integer),
        sa.Column("anticipations_matched", sa.Integer),
        sa.Column("anticipations_total", sa.Integer),
        sa.Column("c197_records_inserted", sa.Integer),
        sa.Column("e111_records_inserted", sa.Integer),
        sa.Column("e116_records_inserted", sa.Integer),
        sa.Column("error_message", sa.Text),
        sa.Column("processing_started_at", sa.DateTime(timezone=True)),
        sa.Column("processing_finished_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    # job_logs
    op.create_table(
        "job_logs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("job_id", sa.String(36), sa.ForeignKey("processing_jobs.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column(
            "level",
            sa.Enum("INFO", "WARN", "ERROR", name="loglevel"),
            nullable=False,
            default="INFO",
        ),
        sa.Column("message", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    # anticipation_records
    op.create_table(
        "anticipation_records",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("job_id", sa.String(36), sa.ForeignKey("processing_jobs.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("chave_nfe", sa.String(44)),
        sa.Column("numero_nf", sa.String(20)),
        sa.Column("serie_nf", sa.String(5)),
        sa.Column("emitente_cnpj", sa.String(14)),
        sa.Column(
            "tipo_antecipacao",
            sa.Enum("NORMAL", "ESPECIAL", "CESTA_BASICA", name="tipoantecipacao"),
            nullable=False,
        ),
        sa.Column("valor_icms", sa.Numeric(15, 2), nullable=False),
        sa.Column("codigo_ajuste", sa.String(20)),
        sa.Column("dare_numero", sa.String(50)),
        sa.Column("dare_vencimento", sa.Date),
        sa.Column("matched", sa.Boolean, nullable=False, default=False),
    )


def downgrade() -> None:
    op.drop_table("anticipation_records")
    op.drop_table("job_logs")
    op.drop_table("processing_jobs")
    op.drop_table("companies")
    op.drop_table("users")
    op.drop_table("accounting_firms")
    op.drop_table("subscriptions")
    op.execute("DROP TYPE IF EXISTS tipoantecipacao")
    op.execute("DROP TYPE IF EXISTS loglevel")
    op.execute("DROP TYPE IF EXISTS jobstatus")
    op.execute("DROP TYPE IF EXISTS userrole")
    op.execute("DROP TYPE IF EXISTS subscriptionstatus")
    op.execute("DROP TYPE IF EXISTS subscriptionplan")
