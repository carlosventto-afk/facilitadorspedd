"""Testes de API para rotas scoped ao escritório (routes/firms.py)."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.db.models import (
    AccountingFirm,
    Company,
    CreditStatus,
    PendingAntecipacaoCredit,
    User,
    UserRole,
)

from .conftest import auth_headers


async def _create_firmless_gestor(
    db: AsyncSession, email: str = "sem.escritorio@teste.com.br"
) -> User:
    user = User(
        email=email,
        password_hash=hash_password("Senha@123"),
        full_name="Gestor Sem Escritório",
        role=UserRole.GESTOR,
        accounting_firm_id=None,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def _create_operator(
    db: AsyncSession, accounting_firm: AccountingFirm, email: str = "operador@teste.com.br",
) -> User:
    user = User(
        email=email,
        password_hash=hash_password("Senha@123"),
        full_name="Operador Teste",
        role=UserRole.OPERADOR,
        accounting_firm_id=accounting_firm.id,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


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


# ── POST /firms (Gestor cria o próprio escritório) ─────────────────────────────

async def test_gestor_sem_escritorio_cria_o_proprio(client: AsyncClient, db: AsyncSession) -> None:
    gestor = await _create_firmless_gestor(db)
    r = await client.post(
        "/firms",
        json={
            "name": "Meu Escritório LTDA",
            "cpf_cnpj": "44555666000177",
            "email": "contato@meuescritorio.com.br",
        },
        headers=auth_headers(gestor),
    )
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["subscription"]["plan"] == "STARTER"
    assert data["subscription"]["status"] == "TRIALING"

    # o Gestor ficou vinculado ao escritório recém-criado
    r_me = await client.get("/firms/me", headers=auth_headers(gestor))
    assert r_me.status_code == 200
    assert r_me.json()["id"] == data["id"]


async def test_gestor_que_ja_tem_escritorio_recebe_409(
    client: AsyncClient, gestor_user: User,
) -> None:
    r = await client.post(
        "/firms",
        json={"name": "Outro", "cpf_cnpj": "77888999000155", "email": "outro@teste.com.br"},
        headers=auth_headers(gestor_user),
    )
    assert r.status_code == 409


async def test_gestor_sem_escritorio_cria_o_proprio_com_cpf(
    client: AsyncClient, db: AsyncSession,
) -> None:
    """Contador autônomo (profissional liberal) sem CNPJ — cadastra o
    escritório usando o próprio CPF."""
    gestor = await _create_firmless_gestor(db)
    r = await client.post(
        "/firms",
        json={
            "name": "Contador Autônomo",
            "cpf_cnpj": "529.982.247-25",
            "email": "contador@teste.com.br",
        },
        headers=auth_headers(gestor),
    )
    assert r.status_code == 201, r.text
    assert r.json()["cpf_cnpj"] == "52998224725"


async def test_criar_escritorio_documento_com_quantidade_invalida_de_digitos_retorna_422(
    client: AsyncClient, db: AsyncSession,
) -> None:
    gestor = await _create_firmless_gestor(db)
    r = await client.post(
        "/firms",
        json={"name": "X", "cpf_cnpj": "123456789", "email": "x@teste.com.br"},
        headers=auth_headers(gestor),
    )
    assert r.status_code == 422


async def test_criar_escritorio_cnpj_duplicado_retorna_409(
    client: AsyncClient, db: AsyncSession, accounting_firm: AccountingFirm,
) -> None:
    gestor = await _create_firmless_gestor(db)
    r = await client.post(
        "/firms",
        json={
            "name": "Escritório Duplicado",
            "cpf_cnpj": accounting_firm.cpf_cnpj,
            "email": "duplicado@teste.com.br",
        },
        headers=auth_headers(gestor),
    )
    assert r.status_code == 409


async def test_operador_nao_pode_criar_escritorio(client: AsyncClient, db: AsyncSession) -> None:
    operador = User(
        email="operador.sem.firma@teste.com.br",
        password_hash=hash_password("Senha@123"),
        full_name="Operador",
        role=UserRole.OPERADOR,
        accounting_firm_id=None,
    )
    db.add(operador)
    await db.commit()
    await db.refresh(operador)

    r = await client.post(
        "/firms",
        json={"name": "X", "cpf_cnpj": "11122233000144", "email": "x@teste.com.br"},
        headers=auth_headers(operador),
    )
    assert r.status_code == 403


async def test_admin_nao_pode_criar_escritorio_via_post_firms(
    client: AsyncClient, admin_user: User,
) -> None:
    """POST /firms é exclusivo de GESTOR — ADMIN já tem o próprio caminho
    (POST /admin/accounting-firms) e não deveria acabar "dono" de um
    escritório."""
    r = await client.post(
        "/firms",
        json={"name": "X", "cpf_cnpj": "99988877000166", "email": "x@teste.com.br"},
        headers=auth_headers(admin_user),
    )
    assert r.status_code == 403


# ── Vínculo Operador↔Empresa ────────────────────────────────────────────────

async def test_vincular_empresas_a_operador_e_listar(
    client: AsyncClient, db: AsyncSession, accounting_firm: AccountingFirm,
    company: Company, gestor_user: User,
) -> None:
    operador = await _create_operator(db, accounting_firm)
    company2 = Company(
        accounting_firm_id=accounting_firm.id, name="Segunda Empresa", cnpj="55444333000122",
        uf="PA",
    )
    db.add(company2)
    await db.commit()
    await db.refresh(company2)

    r = await client.put(
        f"/firms/me/users/{operador.id}/companies",
        json={"company_ids": [company.id, company2.id]},
        headers=auth_headers(gestor_user),
    )
    assert r.status_code == 200, r.text
    assert {c["id"] for c in r.json()} == {company.id, company2.id}

    r_get = await client.get(
        f"/firms/me/users/{operador.id}/companies", headers=auth_headers(gestor_user),
    )
    assert r_get.status_code == 200
    assert {c["id"] for c in r_get.json()} == {company.id, company2.id}


async def test_substituir_vinculo_remove_o_que_nao_esta_mais_na_lista(
    client: AsyncClient, db: AsyncSession, accounting_firm: AccountingFirm,
    company: Company, gestor_user: User,
) -> None:
    operador = await _create_operator(db, accounting_firm)
    company2 = Company(
        accounting_firm_id=accounting_firm.id, name="Segunda Empresa", cnpj="55444333000122",
        uf="PA",
    )
    db.add(company2)
    await db.commit()
    await db.refresh(company2)

    await client.put(
        f"/firms/me/users/{operador.id}/companies",
        json={"company_ids": [company.id, company2.id]},
        headers=auth_headers(gestor_user),
    )
    r = await client.put(
        f"/firms/me/users/{operador.id}/companies",
        json={"company_ids": [company2.id]},
        headers=auth_headers(gestor_user),
    )
    assert r.status_code == 200
    assert [c["id"] for c in r.json()] == [company2.id]


async def test_vincular_empresa_de_outro_escritorio_retorna_400(
    client: AsyncClient, db: AsyncSession, accounting_firm: AccountingFirm, gestor_user: User,
) -> None:
    operador = await _create_operator(db, accounting_firm)
    outro_firm = AccountingFirm(
        name="Outro Escritório", cpf_cnpj="66777888000133", email="outro@teste.com.br",
    )
    db.add(outro_firm)
    await db.commit()
    await db.refresh(outro_firm)
    empresa_alheia = Company(
        accounting_firm_id=outro_firm.id, name="Empresa Alheia", cnpj="11223344000155", uf="PA",
    )
    db.add(empresa_alheia)
    await db.commit()
    await db.refresh(empresa_alheia)

    r = await client.put(
        f"/firms/me/users/{operador.id}/companies",
        json={"company_ids": [empresa_alheia.id]},
        headers=auth_headers(gestor_user),
    )
    assert r.status_code == 400


async def test_vincular_usuario_que_nao_e_operador_retorna_404(
    client: AsyncClient, company: Company, gestor_user: User,
) -> None:
    r = await client.put(
        f"/firms/me/users/{gestor_user.id}/companies",
        json={"company_ids": [company.id]},
        headers=auth_headers(gestor_user),
    )
    assert r.status_code == 404


async def test_operador_ve_so_empresas_vinculadas_em_list_companies(
    client: AsyncClient, db: AsyncSession, accounting_firm: AccountingFirm,
    company: Company, gestor_user: User,
) -> None:
    operador = await _create_operator(db, accounting_firm)
    company2 = Company(
        accounting_firm_id=accounting_firm.id, name="Segunda Empresa", cnpj="55444333000122",
        uf="PA",
    )
    db.add(company2)
    await db.commit()
    await db.refresh(company2)

    await client.put(
        f"/firms/me/users/{operador.id}/companies",
        json={"company_ids": [company.id]},
        headers=auth_headers(gestor_user),
    )

    r = await client.get("/firms/me/companies", headers=auth_headers(operador))
    assert r.status_code == 200
    assert [c["id"] for c in r.json()] == [company.id]


async def test_operador_sem_vinculo_ve_lista_vazia_em_list_companies(
    client: AsyncClient, db: AsyncSession, accounting_firm: AccountingFirm,
) -> None:
    operador = await _create_operator(db, accounting_firm)
    r = await client.get("/firms/me/companies", headers=auth_headers(operador))
    assert r.status_code == 200
    assert r.json() == []


async def test_gestor_continua_vendo_todas_as_empresas_do_escritorio(
    client: AsyncClient, db: AsyncSession, accounting_firm: AccountingFirm,
    company: Company, gestor_user: User,
) -> None:
    """Regressão: a mudança pro Operador não deve afetar GESTOR/ADMIN."""
    company2 = Company(
        accounting_firm_id=accounting_firm.id, name="Segunda Empresa", cnpj="55444333000122",
        uf="PA",
    )
    db.add(company2)
    await db.commit()

    r = await client.get("/firms/me/companies", headers=auth_headers(gestor_user))
    assert r.status_code == 200
    assert len(r.json()) == 2
