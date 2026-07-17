from pydantic import BaseModel, field_validator


class CompanyCreate(BaseModel):
    name: str
    cnpj: str
    inscricao_estadual: str | None = None
    uf: str = "PA"

    @field_validator("cnpj")
    @classmethod
    def clean_cnpj(cls, v: str) -> str:
        digits = "".join(c for c in v if c.isdigit())
        if len(digits) != 14:
            raise ValueError("CNPJ deve ter 14 dígitos")
        return digits

    @field_validator("uf")
    @classmethod
    def upper_uf(cls, v: str) -> str:
        return v.upper()


class CompanyUpdate(BaseModel):
    name: str | None = None
    inscricao_estadual: str | None = None
    is_active: bool | None = None


class CompanyRead(BaseModel):
    id: str
    accounting_firm_id: str
    name: str
    cnpj: str
    inscricao_estadual: str | None
    uf: str
    is_active: bool

    model_config = {"from_attributes": True}
