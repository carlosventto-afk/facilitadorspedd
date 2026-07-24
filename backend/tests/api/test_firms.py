"""Testes de API para rotas scoped ao escritório (routes/firms.py)."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Company, CreditStatus, PendingAntecipacaoCredit, User

from .conftest import auth_headers


async def _make_job_id(
    db: AsyncSession, company: Company, gestor_user: User, period_end: date
) -> str:
    """Cria um ProcessingJob mínimo (dummy) só pra servir de source_job_id
    de um PendingAntecipacaoCredit — o teste não processa nada de verdade."""
    from app.db.models import JobStatus, ProcessingJob

    job = ProcessingJob(
        company_id=company.id,
        created_by=gestor_user.id,
        status=JobStatus.COMPLETED,
        period_start=period_end.replace(day=1),
        period_end=period_end,
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)
    return job.id


# ── GET /me/companies/{id}/pending-credits ────────────────────────────────────

async def test_pending_credits_vazio_quando_nao_ha_credito(
    client: AsyncClient, company: Company, gestor_user: User,
) -> None:
    r = await client.get(
        f"/firms/me/companies/{company.id}/pending-credits", headers=auth_headers(gestor_user),
    )
    assert r.status_code == 200
    assert r.json() == []


async def test_pending_credits_lista_pending_e_claimed_mais_recente_primeiro(
    client: AsyncClient, db: AsyncSession, company: Company, gestor_user: User,
) -> None:
    job_jan = await _make_job_id(db, company, gestor_user, date(2026, 1, 31))
    job_fev = await _make_job_id(db, company, gestor_user, date(2026, 2, 28))

    db.add(PendingAntecipacaoCredit(
        company_id=company.id, competencia_origem=date(2026, 1, 31),
        valor=Decimal("100.00"), status=CreditStatus.CLAIMED,
        source_job_id=job_jan, claimed_in_job_id=job_fev,
    ))
    db.add(PendingAntecipacaoCredit(
        company_id=company.id, competencia_origem=date(2026, 2, 28),
        valor=Decimal("250.50"), status=CreditStatus.PENDING,
        source_job_id=job_fev, claimed_in_job_id=None,
    ))
    await db.commit()

    r = await client.get(
        f"/firms/me/companies/{company.id}/pending-credits", headers=auth_headers(gestor_user),
    )
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 2

    # Mais recente (competencia_origem) primeiro
    assert data[0]["competencia_origem"] == "2026-02-28"
    assert data[0]["status"] == "PENDING"
    assert data[0]["valor"] == "250.50"
    assert data[0]["claimed_in_job_id"] is None

    assert data[1]["competencia_origem"] == "2026-01-31"
    assert data[1]["status"] == "CLAIMED"
    assert data[1]["valor"] == "100.00"
    assert data[1]["claimed_in_job_id"] == job_fev


async def test_pending_credits_404_para_empresa_de_outro_escritorio(
    client: AsyncClient, gestor_user: User,
) -> None:
    r = await client.get(
        "/firms/me/companies/id-que-nao-existe/pending-credits", headers=auth_headers(gestor_user),
    )
    assert r.status_code == 404
