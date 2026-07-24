from pydantic import BaseModel, EmailStr

from app.db.models import UserRole


class UserCreate(BaseModel):
    email: EmailStr
    password: str
    full_name: str
    role: UserRole = UserRole.OPERADOR
    accounting_firm_id: str | None = None


class UserUpdate(BaseModel):
    full_name: str | None = None
    is_active: bool | None = None


class UserRead(BaseModel):
    id: str
    email: str
    full_name: str
    role: UserRole
    is_active: bool
    accounting_firm_id: str | None

    model_config = {"from_attributes": True}


class OperatorCompanyLinksUpdate(BaseModel):
    """Substitui o conjunto INTEIRO de empresas vinculadas a um Operador —
    não é incremental (ver PUT /firms/me/users/{operator_id}/companies)."""

    company_ids: list[str]
