from datetime import date
from decimal import Decimal

from pydantic import BaseModel, field_validator

from app.db.models import CreditStatus


class CnpjRegistryData(BaseModel):
    """Dados cadastrais do CNPJ (Receita Federal) — comuns entre criação,
    atualização e leitura de empresa, e ao resultado da consulta automática
    (ver CnpjLookupResult e GET /firms/me/cnpj/{cnpj})."""

    nome_fantasia: str | None = None
    situacao_cadastral: str | None = None
    data_abertura: date | None = None
    natureza_juridica: str | None = None
    porte: str | None = None
    cnae_principal: str | None = None
    cnae_descricao: str | None = None
    telefone: str | None = None
    email: str | None = None
    cep: str | None = None
    logradouro: str | None = None
    numero: str | None = None
    complemento: str | None = None
    bairro: str | None = None
    municipio: str | None = None


class CompanyCreate(CnpjRegistryData):
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


class CompanyUpdate(CnpjRegistryData):
    name: str | None = None
    inscricao_estadual: str | None = None
    is_active: bool | None = None


class AdminCompanyCreate(CompanyCreate):
    """Igual a CompanyCreate, mas com o escritório explícito — usado só por
    POST /admin/companies. No fluxo do Gestor (POST /firms/me/companies) o
    escritório é implícito do usuário logado; o Admin opera cross-firm, então
    precisa escolher pra qual escritório a empresa vai."""

    accounting_firm_id: str


class CompanyRead(CnpjRegistryData):
    id: str
    accounting_firm_id: str
    name: str
    cnpj: str
    inscricao_estadual: str | None
    uf: str
    is_active: bool

    model_config = {"from_attributes": True}


class CnpjLookupResult(CnpjRegistryData):
    """Resultado da consulta pública de CNPJ (Receita Federal, via BrasilAPI)
    — usado pelo frontend para pré-preencher o formulário de cadastro."""

    name: str
    uf: str


class PendingCreditRead(BaseModel):
    """Crédito ESPECIAL apurado num período mas ainda não lançado (E111) —
    orientação SEFA-PA 1173 §2, ver app/sped/writer.py. PENDING = à espera
    do próximo período processado desta empresa; CLAIMED = já lançado."""

    id: str
    competencia_origem: date
    valor: Decimal
    status: CreditStatus
    source_job_id: str
    claimed_in_job_id: str | None

    model_config = {"from_attributes": True}
