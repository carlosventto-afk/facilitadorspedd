from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.v1.schemas.companies import AdminCompanyCreate, CompanyRead, CompanyUpdate
from app.api.v1.schemas.firms import AccountingFirmCreate, AccountingFirmRead, AccountingFirmUpdate
from app.api.v1.schemas.invitations import InvitationCreate, InvitationRead
from app.api.v1.schemas.users import UserCreate, UserRead, UserUpdate
from app.core.config import settings
from app.core.deps import AdminUser
from app.core.email import send_email
from app.core.security import create_invite_token, hash_password
from app.db.models import (
    AccountingFirm,
    Company,
    Invitation,
    InvitationStatus,
    JobStatus,
    ProcessingJob,
    Subscription,
    SubscriptionPlan,
    SubscriptionStatus,
    User,
    UserRole,
)
from app.db.session import get_db

router = APIRouter(prefix="/admin", tags=["admin"])

PLAN_LIMITS = {
    SubscriptionPlan.STARTER: {"max_companies": 5, "max_jobs_per_month": 20},
    SubscriptionPlan.PROFESSIONAL: {"max_companies": 30, "max_jobs_per_month": 150},
    SubscriptionPlan.ENTERPRISE: {"max_companies": 9999, "max_jobs_per_month": 9999},
}


# ─── Accounting Firms ─────────────────────────────────────────────────────────

@router.get("/accounting-firms", response_model=list[AccountingFirmRead])
async def list_firms(
    _: AdminUser,
    db: Annotated[AsyncSession, Depends(get_db)],
    skip: int = 0,
    limit: int = 50,
) -> list[AccountingFirm]:
    result = await db.execute(
        select(AccountingFirm)
        .options(selectinload(AccountingFirm.subscription))
        .offset(skip)
        .limit(limit)
        .order_by(AccountingFirm.created_at.desc())
    )
    return list(result.scalars().all())


@router.post("/accounting-firms", response_model=AccountingFirmRead, status_code=status.HTTP_201_CREATED)
async def create_firm(
    _: AdminUser,
    payload: AccountingFirmCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> AccountingFirm:
    existing = await db.execute(select(AccountingFirm).where(AccountingFirm.cnpj == payload.cnpj))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="CNPJ já cadastrado")

    limits = PLAN_LIMITS[payload.plan]
    subscription = Subscription(
        plan=payload.plan,
        status=SubscriptionStatus.TRIALING,
        max_companies=limits["max_companies"],
        max_jobs_per_month=limits["max_jobs_per_month"],
    )
    db.add(subscription)
    await db.flush()

    firm = AccountingFirm(
        name=payload.name,
        cnpj=payload.cnpj,
        email=payload.email.lower(),
        phone=payload.phone,
        subscription_id=subscription.id,
    )
    db.add(firm)
    await db.commit()
    await db.refresh(firm)

    # reload with subscription
    result = await db.execute(
        select(AccountingFirm)
        .options(selectinload(AccountingFirm.subscription))
        .where(AccountingFirm.id == firm.id)
    )
    return result.scalar_one()


@router.get("/accounting-firms/{firm_id}", response_model=AccountingFirmRead)
async def get_firm(
    firm_id: str,
    _: AdminUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> AccountingFirm:
    result = await db.execute(
        select(AccountingFirm)
        .options(selectinload(AccountingFirm.subscription))
        .where(AccountingFirm.id == firm_id)
    )
    firm = result.scalar_one_or_none()
    if not firm:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Escritório não encontrado")
    return firm


@router.patch("/accounting-firms/{firm_id}", response_model=AccountingFirmRead)
async def update_firm(
    firm_id: str,
    payload: AccountingFirmUpdate,
    _: AdminUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> AccountingFirm:
    result = await db.execute(
        select(AccountingFirm)
        .options(selectinload(AccountingFirm.subscription))
        .where(AccountingFirm.id == firm_id)
    )
    firm = result.scalar_one_or_none()
    if not firm:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Escritório não encontrado")

    updates = payload.model_dump(exclude_none=True)
    # "plan" não é coluna de AccountingFirm (mora em Subscription) — não pode
    # entrar no loop genérico de setattr abaixo. Trocar de plano precisa
    # resincronizar os limites (max_companies/max_jobs_per_month) também,
    # senão o escritório fica com o plano novo mas os limites do antigo.
    new_plan = updates.pop("plan", None)
    if new_plan is not None and firm.subscription is not None:
        limits = PLAN_LIMITS[new_plan]
        firm.subscription.plan = new_plan
        firm.subscription.max_companies = limits["max_companies"]
        firm.subscription.max_jobs_per_month = limits["max_jobs_per_month"]

    for field, value in updates.items():
        setattr(firm, field, value)

    await db.commit()
    await db.refresh(firm)
    return firm


# ─── Users ────────────────────────────────────────────────────────────────────

@router.get("/users", response_model=list[UserRead])
async def list_users(
    _: AdminUser,
    db: Annotated[AsyncSession, Depends(get_db)],
    skip: int = 0,
    limit: int = 50,
) -> list[User]:
    result = await db.execute(
        select(User).offset(skip).limit(limit).order_by(User.created_at.desc())
    )
    return list(result.scalars().all())


@router.post("/users", response_model=UserRead, status_code=status.HTTP_201_CREATED)
async def create_user(
    payload: UserCreate,
    _: AdminUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    existing = await db.execute(select(User).where(User.email == payload.email.lower()))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email já cadastrado")

    user = User(
        email=payload.email.lower(),
        password_hash=hash_password(payload.password),
        full_name=payload.full_name,
        role=payload.role,
        accounting_firm_id=payload.accounting_firm_id,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


@router.patch("/users/{user_id}", response_model=UserRead)
async def update_user(
    user_id: str,
    payload: UserUpdate,
    _: AdminUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Usuário não encontrado")

    for field, value in payload.model_dump(exclude_none=True).items():
        setattr(user, field, value)

    await db.commit()
    await db.refresh(user)
    return user


# ─── Invitations (convite de Gestor por e-mail) ────────────────────────────────

@router.post("/invitations", response_model=InvitationRead, status_code=status.HTTP_201_CREATED)
async def create_invitation(
    payload: InvitationCreate,
    current_user: AdminUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Invitation:
    email = payload.email.lower()

    firm = await db.execute(
        select(AccountingFirm).where(AccountingFirm.id == payload.accounting_firm_id)
    )
    if not firm.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Escritório não encontrado"
        )

    existing_user = await db.execute(select(User).where(User.email == email))
    if existing_user.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Já existe um usuário cadastrado com este e-mail",
        )

    existing_invite = await db.execute(
        select(Invitation).where(
            Invitation.email == email, Invitation.status == InvitationStatus.PENDING
        )
    )
    if existing_invite.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Já existe um convite pendente para este e-mail. Cancele o "
                "convite existente antes de enviar um novo."
            ),
        )

    invitation = Invitation(
        email=email,
        accounting_firm_id=payload.accounting_firm_id,
        invited_by=current_user.id,
    )
    db.add(invitation)
    await db.commit()
    await db.refresh(invitation)

    token = create_invite_token(invitation.id)
    invite_link = f"{settings.FRONTEND_URL}/accept-invite?token={token}"
    await send_email(
        to=invitation.email,
        subject="Convite — FacilitadorSped",
        html_content=(
            f"<p>Você foi convidado a se cadastrar como Gestor no FacilitadorSped.</p>"
            f"<p>Clique no link abaixo para definir seu nome e senha:</p>"
            f'<p><a href="{invite_link}">{invite_link}</a></p>'
            f"<p>Este link expira em {settings.INVITE_TOKEN_EXPIRE_DAYS} dias.</p>"
        ),
    )

    return invitation


@router.get("/invitations", response_model=list[InvitationRead])
async def list_invitations(
    _: AdminUser,
    db: Annotated[AsyncSession, Depends(get_db)],
    skip: int = 0,
    limit: int = 50,
) -> list[Invitation]:
    result = await db.execute(
        select(Invitation).offset(skip).limit(limit).order_by(Invitation.created_at.desc())
    )
    return list(result.scalars().all())


@router.delete("/invitations/{invitation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def cancel_invitation(
    invitation_id: str,
    _: AdminUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    result = await db.execute(select(Invitation).where(Invitation.id == invitation_id))
    invitation = result.scalar_one_or_none()
    if not invitation:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Convite não encontrado")
    if invitation.status != InvitationStatus.PENDING:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Convite não está mais pendente"
        )

    invitation.status = InvitationStatus.CANCELED
    await db.commit()


# ─── Companies (cross-firm) ────────────────────────────────────────────────────

@router.get("/companies", response_model=list[CompanyRead])
async def list_companies(
    _: AdminUser,
    db: Annotated[AsyncSession, Depends(get_db)],
    skip: int = 0,
    limit: int = 50,
) -> list[Company]:
    result = await db.execute(
        select(Company).offset(skip).limit(limit).order_by(Company.created_at.desc())
    )
    return list(result.scalars().all())


@router.post("/companies", response_model=CompanyRead, status_code=status.HTTP_201_CREATED)
async def create_company(
    payload: AdminCompanyCreate,
    _: AdminUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Company:
    firm = await db.execute(
        select(AccountingFirm).where(AccountingFirm.id == payload.accounting_firm_id)
    )
    if not firm.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Escritório não encontrado"
        )

    existing = await db.execute(
        select(Company).where(
            Company.accounting_firm_id == payload.accounting_firm_id,
            Company.cnpj == payload.cnpj,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Empresa com este CNPJ já cadastrada"
        )

    company = Company(**payload.model_dump())
    db.add(company)
    await db.commit()
    await db.refresh(company)
    return company


@router.patch("/companies/{company_id}", response_model=CompanyRead)
async def update_company(
    company_id: str,
    payload: CompanyUpdate,
    _: AdminUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Company:
    result = await db.execute(select(Company).where(Company.id == company_id))
    company = result.scalar_one_or_none()
    if not company:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Empresa não encontrada")

    for field, value in payload.model_dump(exclude_none=True).items():
        setattr(company, field, value)

    await db.commit()
    await db.refresh(company)
    return company


# ─── Global Stats ─────────────────────────────────────────────────────────────

@router.get("/stats")
async def get_stats(
    _: AdminUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    total_firms = (await db.execute(func.count(AccountingFirm.id).select())).scalar() or 0
    active_subs = (
        await db.execute(
            select(func.count(Subscription.id)).where(Subscription.status == SubscriptionStatus.ACTIVE)
        )
    ).scalar() or 0
    total_jobs = (await db.execute(func.count(ProcessingJob.id).select())).scalar() or 0
    failed_jobs = (
        await db.execute(
            select(func.count(ProcessingJob.id)).where(ProcessingJob.status == JobStatus.FAILED)
        )
    ).scalar() or 0

    return {
        "total_accounting_firms": total_firms,
        "active_subscriptions": active_subs,
        "total_jobs_processed": total_jobs,
        "failed_jobs": failed_jobs,
    }
