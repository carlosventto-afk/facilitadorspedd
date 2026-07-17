import enum
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, new_uuid


class UserRole(str, enum.Enum):
    ADMIN = "ADMIN"
    GESTOR = "GESTOR"
    OPERADOR = "OPERADOR"


class SubscriptionPlan(str, enum.Enum):
    STARTER = "STARTER"
    PROFESSIONAL = "PROFESSIONAL"
    ENTERPRISE = "ENTERPRISE"


class SubscriptionStatus(str, enum.Enum):
    TRIALING = "TRIALING"
    ACTIVE = "ACTIVE"
    PAST_DUE = "PAST_DUE"
    CANCELED = "CANCELED"


class JobStatus(str, enum.Enum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class TipoAntecipacao(str, enum.Enum):
    NORMAL = "NORMAL"
    ESPECIAL = "ESPECIAL"
    CESTA_BASICA = "CESTA_BASICA"


class LogLevel(str, enum.Enum):
    INFO = "INFO"
    WARN = "WARN"
    ERROR = "ERROR"


# ─── Subscription ────────────────────────────────────────────────────────────

class Subscription(Base, TimestampMixin):
    __tablename__ = "subscriptions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    plan: Mapped[SubscriptionPlan] = mapped_column(Enum(SubscriptionPlan), nullable=False)
    status: Mapped[SubscriptionStatus] = mapped_column(
        Enum(SubscriptionStatus), nullable=False, default=SubscriptionStatus.TRIALING
    )
    stripe_subscription_id: Mapped[str | None] = mapped_column(String(255))
    stripe_customer_id: Mapped[str | None] = mapped_column(String(255))
    current_period_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    current_period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    max_companies: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    max_jobs_per_month: Mapped[int] = mapped_column(Integer, nullable=False, default=20)

    # back-ref
    accounting_firm: Mapped["AccountingFirm"] = relationship(back_populates="subscription")


# ─── Accounting Firm ──────────────────────────────────────────────────────────

class AccountingFirm(Base, TimestampMixin):
    __tablename__ = "accounting_firms"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    cnpj: Mapped[str] = mapped_column(String(14), unique=True, nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(20))
    subscription_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("subscriptions.id", ondelete="SET NULL")
    )

    subscription: Mapped["Subscription | None"] = relationship(back_populates="accounting_firm")
    users: Mapped[list["User"]] = relationship(back_populates="accounting_firm")
    companies: Mapped[list["Company"]] = relationship(back_populates="accounting_firm")


# ─── User ─────────────────────────────────────────────────────────────────────

class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(Enum(UserRole), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    accounting_firm_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("accounting_firms.id", ondelete="SET NULL")
    )

    accounting_firm: Mapped["AccountingFirm | None"] = relationship(back_populates="users")
    created_jobs: Mapped[list["ProcessingJob"]] = relationship(back_populates="created_by_user")


# ─── Company (client of accounting firm) ─────────────────────────────────────

class Company(Base, TimestampMixin):
    __tablename__ = "companies"
    __table_args__ = (UniqueConstraint("accounting_firm_id", "cnpj", name="uq_firm_company_cnpj"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    accounting_firm_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("accounting_firms.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    cnpj: Mapped[str] = mapped_column(String(14), nullable=False)
    inscricao_estadual: Mapped[str | None] = mapped_column(String(50))
    uf: Mapped[str] = mapped_column(String(2), nullable=False, default="PA")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    accounting_firm: Mapped["AccountingFirm"] = relationship(back_populates="companies")
    jobs: Mapped[list["ProcessingJob"]] = relationship(back_populates="company")


# ─── Processing Job ───────────────────────────────────────────────────────────

class ProcessingJob(Base, TimestampMixin):
    __tablename__ = "processing_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    company_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False
    )
    created_by: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=False
    )
    status: Mapped[JobStatus] = mapped_column(
        Enum(JobStatus), nullable=False, default=JobStatus.PENDING
    )
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)

    # S3 keys
    sped_input_s3_key: Mapped[str | None] = mapped_column(String(500))
    excel_input_s3_key: Mapped[str | None] = mapped_column(String(500))
    sped_output_s3_key: Mapped[str | None] = mapped_column(String(500))

    # Processing stats
    nfs_found: Mapped[int | None] = mapped_column(Integer)
    anticipations_matched: Mapped[int | None] = mapped_column(Integer)
    anticipations_total: Mapped[int | None] = mapped_column(Integer)
    c197_records_inserted: Mapped[int | None] = mapped_column(Integer)
    e111_records_inserted: Mapped[int | None] = mapped_column(Integer)
    e116_records_inserted: Mapped[int | None] = mapped_column(Integer)
    error_message: Mapped[str | None] = mapped_column(Text)
    processing_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    processing_finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    company: Mapped["Company"] = relationship(back_populates="jobs")
    created_by_user: Mapped["User"] = relationship(back_populates="created_jobs")
    logs: Mapped[list["JobLog"]] = relationship(back_populates="job", cascade="all, delete-orphan")
    anticipation_records: Mapped[list["AnticipationRecord"]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )


# ─── Job Log ──────────────────────────────────────────────────────────────────

class JobLog(Base):
    __tablename__ = "job_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    job_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("processing_jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    level: Mapped[LogLevel] = mapped_column(Enum(LogLevel), nullable=False, default=LogLevel.INFO)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    job: Mapped["ProcessingJob"] = relationship(back_populates="logs")


# ─── Anticipation Record ──────────────────────────────────────────────────────

class AnticipationRecord(Base):
    __tablename__ = "anticipation_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    job_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("processing_jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    chave_nfe: Mapped[str | None] = mapped_column(String(44))
    numero_nf: Mapped[str | None] = mapped_column(String(20))
    serie_nf: Mapped[str | None] = mapped_column(String(5))
    emitente_cnpj: Mapped[str | None] = mapped_column(String(14))
    tipo_antecipacao: Mapped[TipoAntecipacao] = mapped_column(Enum(TipoAntecipacao), nullable=False)
    valor_icms: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)
    codigo_ajuste: Mapped[str | None] = mapped_column(String(20))
    dare_numero: Mapped[str | None] = mapped_column(String(50))
    dare_vencimento: Mapped[date | None] = mapped_column(Date)
    matched: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    job: Mapped["ProcessingJob"] = relationship(back_populates="anticipation_records")
