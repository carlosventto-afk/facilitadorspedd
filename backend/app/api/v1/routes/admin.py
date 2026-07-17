from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.v1.schemas.firms import AccountingFirmCreate, AccountingFirmRead, AccountingFirmUpdate
from app.api.v1.schemas.users import UserCreate, UserRead, UserUpdate
from app.core.deps import AdminUser
from app.core.security import hash_password
from app.db.models import (
    AccountingFirm,
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
