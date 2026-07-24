"""Routes scoped to the authenticated Gestor's own accounting firm."""
import asyncio
import logging
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.v1.schemas.companies import (
    CnpjLookupResult,
    CompanyCreate,
    CompanyRead,
    CompanyUpdate,
    PendingCreditRead,
)
from app.api.v1.schemas.firms import AccountingFirmRead, AccountingFirmUpdate, SubscriptionRead
from app.api.v1.schemas.users import UserCreate, UserRead, UserUpdate
from app.core.deps import GestorUser
from app.core.security import hash_password
from app.db.models import (
    AccountingFirm,
    Company,
    PendingAntecipacaoCredit,
    Subscription,
    User,
    UserRole,
)
from app.db.session import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/firms", tags=["firms"])

_BRASILAPI_CNPJ_URL = "https://brasilapi.com.br/api/cnpj/v1/{cnpj}"
# BrasilAPI (plano gratuito) tem rate limit apertado — picos curtos de 429 são
# comuns mesmo em uso normal (1 consulta por cadastro). Absorve automaticamente
# com 2 retries curtos antes de repassar erro pro usuário.
_BRASILAPI_MAX_RETRIES = 2
_BRASILAPI_RETRY_DELAY_SECONDS = 1.5


async def _get_firm_with_sub(firm_id: str, db: AsyncSession) -> AccountingFirm:
    result = await db.execute(
        select(AccountingFirm)
        .options(selectinload(AccountingFirm.subscription))
        .where(AccountingFirm.id == firm_id)
    )
    firm = result.scalar_one_or_none()
    if not firm:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Escritório não encontrado")
    return firm


# ─── Firm Profile ─────────────────────────────────────────────────────────────

@router.get("/me", response_model=AccountingFirmRead)
async def get_my_firm(
    current_user: GestorUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> AccountingFirm:
    if not current_user.accounting_firm_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sem escritório associado")
    return await _get_firm_with_sub(current_user.accounting_firm_id, db)


@router.patch("/me", response_model=AccountingFirmRead)
async def update_my_firm(
    payload: AccountingFirmUpdate,
    current_user: GestorUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> AccountingFirm:
    if not current_user.accounting_firm_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sem escritório associado")

    firm = await _get_firm_with_sub(current_user.accounting_firm_id, db)
    for field, value in payload.model_dump(exclude_none=True).items():
        setattr(firm, field, value)

    await db.commit()
    await db.refresh(firm)
    return firm


# ─── Subscription ─────────────────────────────────────────────────────────────

@router.get("/me/subscription", response_model=SubscriptionRead)
async def get_my_subscription(
    current_user: GestorUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Subscription:
    if not current_user.accounting_firm_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sem escritório associado")

    result = await db.execute(
        select(Subscription)
        .join(AccountingFirm)
        .where(AccountingFirm.id == current_user.accounting_firm_id)
    )
    sub = result.scalar_one_or_none()
    if not sub:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assinatura não encontrada")
    return sub


# ─── CNPJ Lookup ──────────────────────────────────────────────────────────────

@router.get("/me/cnpj/{cnpj}", response_model=CnpjLookupResult)
async def lookup_cnpj(cnpj: str, current_user: GestorUser) -> CnpjLookupResult:
    """Consulta os dados cadastrais de um CNPJ na Receita Federal (via
    BrasilAPI, pública e sem chave) — usado pelo frontend para pré-preencher
    o formulário de cadastro de empresa a partir do CNPJ informado."""
    digits = "".join(c for c in cnpj if c.isdigit())
    if len(digits) != 14:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="CNPJ deve ter 14 dígitos"
        )

    async with httpx.AsyncClient(timeout=10.0) as client:
        for attempt in range(_BRASILAPI_MAX_RETRIES + 1):
            try:
                resp = await client.get(_BRASILAPI_CNPJ_URL.format(cnpj=digits))
            except httpx.RequestError as exc:
                logger.warning("Falha ao consultar CNPJ %s na BrasilAPI: %s", digits, exc)
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY, detail="Erro ao consultar CNPJ"
                ) from exc

            if resp.status_code != 429 or attempt == _BRASILAPI_MAX_RETRIES:
                break
            logger.info(
                "BrasilAPI rate limited (429) para CNPJ %s — retry %d/%d em %.1fs",
                digits, attempt + 1, _BRASILAPI_MAX_RETRIES, _BRASILAPI_RETRY_DELAY_SECONDS,
            )
            await asyncio.sleep(_BRASILAPI_RETRY_DELAY_SECONDS)

    if resp.status_code == 404:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="CNPJ não encontrado")
    if resp.status_code == 400:
        # BrasilAPI usa 400 para CNPJ com dígito verificador inválido (formato
        # correto de 14 dígitos, mas checksum não bate) — distinto de "não
        # encontrado" (404, CNPJ válido mas fora da base da Receita).
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="CNPJ inválido")
    if resp.status_code == 429:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Consulta de CNPJ temporariamente indisponível (limite de "
                "requisições) — tente novamente em alguns segundos"
            ),
        )
    if resp.status_code != 200:
        logger.warning("BrasilAPI retornou %d para CNPJ %s", resp.status_code, digits)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Erro ao consultar CNPJ na Receita Federal",
        )

    data = resp.json()
    telefone = data.get("ddd_telefone_1") or None
    cnae_fiscal = data.get("cnae_fiscal")

    return CnpjLookupResult(
        name=data.get("razao_social") or "",
        uf=data.get("uf") or "",
        nome_fantasia=data.get("nome_fantasia") or None,
        situacao_cadastral=data.get("descricao_situacao_cadastral"),
        data_abertura=data.get("data_inicio_atividade"),
        natureza_juridica=data.get("natureza_juridica"),
        porte=data.get("porte"),
        cnae_principal=str(cnae_fiscal) if cnae_fiscal else None,
        cnae_descricao=data.get("cnae_fiscal_descricao"),
        telefone=telefone,
        email=data.get("email") or None,
        cep=data.get("cep"),
        logradouro=data.get("logradouro"),
        numero=data.get("numero"),
        complemento=data.get("complemento") or None,
        bairro=data.get("bairro"),
        municipio=data.get("municipio"),
    )


# ─── Client Companies ─────────────────────────────────────────────────────────

@router.get("/me/companies", response_model=list[CompanyRead])
async def list_companies(
    current_user: GestorUser,
    db: Annotated[AsyncSession, Depends(get_db)],
    skip: int = 0,
    limit: int = 100,
) -> list[Company]:
    result = await db.execute(
        select(Company)
        .where(Company.accounting_firm_id == current_user.accounting_firm_id)
        .offset(skip)
        .limit(limit)
        .order_by(Company.name)
    )
    return list(result.scalars().all())


@router.post("/me/companies", response_model=CompanyRead, status_code=status.HTTP_201_CREATED)
async def create_company(
    payload: CompanyCreate,
    current_user: GestorUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Company:
    existing = await db.execute(
        select(Company).where(
            Company.accounting_firm_id == current_user.accounting_firm_id,
            Company.cnpj == payload.cnpj,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Empresa com este CNPJ já cadastrada")

    company = Company(
        accounting_firm_id=current_user.accounting_firm_id,
        **payload.model_dump(),
    )
    db.add(company)
    await db.commit()
    await db.refresh(company)
    return company


@router.get("/me/companies/{company_id}", response_model=CompanyRead)
async def get_company(
    company_id: str,
    current_user: GestorUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Company:
    result = await db.execute(
        select(Company).where(
            Company.id == company_id,
            Company.accounting_firm_id == current_user.accounting_firm_id,
        )
    )
    company = result.scalar_one_or_none()
    if not company:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Empresa não encontrada")
    return company


@router.get("/me/companies/{company_id}/pending-credits", response_model=list[PendingCreditRead])
async def list_pending_credits(
    company_id: str,
    current_user: GestorUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[PendingAntecipacaoCredit]:
    """Créditos ESPECIAL apurados mas ainda não lançados (E111) — orientação
    SEFA-PA 1173 §2, ver app/sped/writer.py. Inclui PENDING (à espera do
    próximo período processado) e CLAIMED (já lançados), mais recentes
    primeiro — visibilidade pro contador acompanhar, não só um mecanismo
    automático invisível."""
    result = await db.execute(
        select(Company).where(
            Company.id == company_id,
            Company.accounting_firm_id == current_user.accounting_firm_id,
        )
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Empresa não encontrada")

    credits_result = await db.execute(
        select(PendingAntecipacaoCredit)
        .where(PendingAntecipacaoCredit.company_id == company_id)
        .order_by(PendingAntecipacaoCredit.competencia_origem.desc())
    )
    return list(credits_result.scalars().all())


@router.patch("/me/companies/{company_id}", response_model=CompanyRead)
async def update_company(
    company_id: str,
    payload: CompanyUpdate,
    current_user: GestorUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Company:
    result = await db.execute(
        select(Company).where(
            Company.id == company_id,
            Company.accounting_firm_id == current_user.accounting_firm_id,
        )
    )
    company = result.scalar_one_or_none()
    if not company:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Empresa não encontrada")

    for field, value in payload.model_dump(exclude_none=True).items():
        setattr(company, field, value)

    await db.commit()
    await db.refresh(company)
    return company


# ─── Operador Users ───────────────────────────────────────────────────────────

@router.get("/me/users", response_model=list[UserRead])
async def list_operators(
    current_user: GestorUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[User]:
    result = await db.execute(
        select(User).where(
            User.accounting_firm_id == current_user.accounting_firm_id,
            User.role == UserRole.OPERADOR,
        )
    )
    return list(result.scalars().all())


@router.post("/me/users", response_model=UserRead, status_code=status.HTTP_201_CREATED)
async def create_operator(
    payload: UserCreate,
    current_user: GestorUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    existing = await db.execute(select(User).where(User.email == payload.email.lower()))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email já cadastrado")

    user = User(
        email=payload.email.lower(),
        password_hash=hash_password(payload.password),
        full_name=payload.full_name,
        role=UserRole.OPERADOR,
        accounting_firm_id=current_user.accounting_firm_id,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


@router.patch("/me/users/{user_id}", response_model=UserRead)
async def update_operator(
    user_id: str,
    payload: UserUpdate,
    current_user: GestorUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    result = await db.execute(
        select(User).where(
            User.id == user_id,
            User.accounting_firm_id == current_user.accounting_firm_id,
        )
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Usuário não encontrado")

    for field, value in payload.model_dump(exclude_none=True).items():
        setattr(user, field, value)

    await db.commit()
    await db.refresh(user)
    return user


@router.delete("/me/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def deactivate_operator(
    user_id: str,
    current_user: GestorUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    result = await db.execute(
        select(User).where(
            User.id == user_id,
            User.accounting_firm_id == current_user.accounting_firm_id,
        )
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Usuário não encontrado")

    user.is_active = False
    await db.commit()
