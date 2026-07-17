from pydantic import BaseModel, EmailStr, field_validator

from app.db.models import SubscriptionPlan, SubscriptionStatus


class SubscriptionRead(BaseModel):
    id: str
    plan: SubscriptionPlan
    status: SubscriptionStatus
    max_companies: int
    max_jobs_per_month: int

    model_config = {"from_attributes": True}


class AccountingFirmCreate(BaseModel):
    name: str
    cnpj: str
    email: EmailStr
    phone: str | None = None
    plan: SubscriptionPlan = SubscriptionPlan.STARTER

    @field_validator("cnpj")
    @classmethod
    def clean_cnpj(cls, v: str) -> str:
        digits = "".join(c for c in v if c.isdigit())
        if len(digits) != 14:
            raise ValueError("CNPJ deve ter 14 dígitos")
        return digits


class AccountingFirmUpdate(BaseModel):
    name: str | None = None
    email: EmailStr | None = None
    phone: str | None = None
    plan: SubscriptionPlan | None = None
    is_active: bool | None = None


class AccountingFirmRead(BaseModel):
    id: str
    name: str
    cnpj: str
    email: str
    phone: str | None
    is_active: bool
    subscription: SubscriptionRead | None

    model_config = {"from_attributes": True}
