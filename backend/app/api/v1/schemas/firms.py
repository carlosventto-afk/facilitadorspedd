from pydantic import BaseModel, EmailStr, field_validator

from app.db.models import SubscriptionPlan, SubscriptionStatus


class SubscriptionRead(BaseModel):
    id: str
    plan: SubscriptionPlan
    status: SubscriptionStatus
    max_companies: int
    max_jobs_per_month: int

    model_config = {"from_attributes": True}


class _AccountingFirmCreateBase(BaseModel):
    name: str
    cpf_cnpj: str
    email: EmailStr
    phone: str | None = None

    @field_validator("cpf_cnpj")
    @classmethod
    def clean_cpf_cnpj(cls, v: str) -> str:
        digits = "".join(c for c in v if c.isdigit())
        if len(digits) not in (11, 14):
            raise ValueError("CPF deve ter 11 dígitos ou CNPJ 14 dígitos")
        return digits


class AccountingFirmCreate(_AccountingFirmCreateBase):
    plan: SubscriptionPlan = SubscriptionPlan.STARTER


class AccountingFirmSelfCreate(_AccountingFirmCreateBase):
    """Igual a AccountingFirmCreate, mas sem `plan` — usado só por POST /firms
    (Gestor criando o próprio escritório): sempre STARTER/TRIALING no código,
    sem seletor de plano no self-service (mesma decisão de produto já usada
    em /assinatura — mudança de plano é manual)."""


class AccountingFirmUpdate(BaseModel):
    name: str | None = None
    email: EmailStr | None = None
    phone: str | None = None
    plan: SubscriptionPlan | None = None
    is_active: bool | None = None


class AccountingFirmRead(BaseModel):
    id: str
    name: str
    cpf_cnpj: str
    email: str
    phone: str | None
    is_active: bool
    subscription: SubscriptionRead | None

    model_config = {"from_attributes": True}
