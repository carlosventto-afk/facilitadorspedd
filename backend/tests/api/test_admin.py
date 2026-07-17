"""Testes das rotas /admin/* (só role ADMIN)."""
from __future__ import annotations

from httpx import AsyncClient

from app.db.models import AccountingFirm, User

from .conftest import auth_headers


async def _create_firm(client: AsyncClient, headers: dict, cnpj: str = "33444555000166") -> dict:
    r = await client.post(
        "/admin/accounting-firms",
        json={"name": "Escritório Novo LTDA", "cnpj": cnpj, "email": "novo@escritorio.com.br"},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()


# ── Escritórios ──────────────────────────────────────────────────────────────

async def test_criar_e_listar_escritorio(client: AsyncClient, admin_user: User) -> None:
    headers = auth_headers(admin_user)
    firm = await _create_firm(client, headers)
    assert firm["is_active"] is True
    assert firm["subscription"]["plan"] == "STARTER"
    assert firm["subscription"]["max_companies"] == 5

    r = await client.get("/admin/accounting-firms", headers=headers)
    assert r.status_code == 200
    names = [f["name"] for f in r.json()]
    assert "Escritório Novo LTDA" in names
    # a listagem já traz o registro completo (inclui phone), sem precisar de
    # uma segunda chamada GET /accounting-firms/{id} pra editar
    assert "phone" in r.json()[0]


async def test_editar_nome_email_telefone(client: AsyncClient, admin_user: User) -> None:
    headers = auth_headers(admin_user)
    firm = await _create_firm(client, headers)

    r = await client.patch(
        f"/admin/accounting-firms/{firm['id']}",
        json={"name": "Nome Editado", "phone": "9199999999"},
        headers=headers,
    )
    assert r.status_code == 200
    data = r.json()
    assert data["name"] == "Nome Editado"
    assert data["phone"] == "9199999999"
    assert data["subscription"]["plan"] == "STARTER"  # não mudou, não foi enviado


async def test_trocar_plano_resincroniza_limites_da_assinatura(
    client: AsyncClient, admin_user: User,
) -> None:
    headers = auth_headers(admin_user)
    firm = await _create_firm(client, headers)
    assert firm["subscription"]["max_companies"] == 5  # STARTER

    r = await client.patch(
        f"/admin/accounting-firms/{firm['id']}", json={"plan": "ENTERPRISE"}, headers=headers,
    )
    assert r.status_code == 200
    data = r.json()
    assert data["subscription"]["plan"] == "ENTERPRISE"
    assert data["subscription"]["max_companies"] == 9999
    assert data["subscription"]["max_jobs_per_month"] == 9999


async def test_ativar_desativar_escritorio(client: AsyncClient, admin_user: User) -> None:
    headers = auth_headers(admin_user)
    firm = await _create_firm(client, headers)

    r = await client.patch(
        f"/admin/accounting-firms/{firm['id']}", json={"is_active": False}, headers=headers,
    )
    assert r.status_code == 200
    assert r.json()["is_active"] is False

    r = await client.patch(
        f"/admin/accounting-firms/{firm['id']}", json={"is_active": True}, headers=headers,
    )
    assert r.status_code == 200
    assert r.json()["is_active"] is True


async def test_cnpj_duplicado_retorna_409(client: AsyncClient, admin_user: User) -> None:
    headers = auth_headers(admin_user)
    await _create_firm(client, headers, cnpj="11222333000181")
    r = await client.post(
        "/admin/accounting-firms",
        json={"name": "Outro", "cnpj": "11222333000181", "email": "outro@teste.com.br"},
        headers=headers,
    )
    assert r.status_code == 409


# ── Usuários ─────────────────────────────────────────────────────────────────

async def test_criar_gestor_vinculado_a_escritorio(
    client: AsyncClient, admin_user: User, accounting_firm: AccountingFirm,
) -> None:
    headers = auth_headers(admin_user)
    r = await client.post(
        "/admin/users",
        json={
            "email": "novo.gestor@teste.com.br",
            "password": "Senha@123",
            "full_name": "Novo Gestor",
            "role": "GESTOR",
            "accounting_firm_id": accounting_firm.id,
        },
        headers=headers,
    )
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["role"] == "GESTOR"
    assert data["accounting_firm_id"] == accounting_firm.id

    r = await client.get("/admin/users", headers=headers)
    emails = [u["email"] for u in r.json()]
    assert "novo.gestor@teste.com.br" in emails


async def test_email_duplicado_retorna_409(
    client: AsyncClient, admin_user: User, accounting_firm: AccountingFirm,
) -> None:
    headers = auth_headers(admin_user)
    payload = {
        "email": "duplicado@teste.com.br", "password": "Senha@123",
        "full_name": "Fulano", "role": "OPERADOR", "accounting_firm_id": accounting_firm.id,
    }
    r1 = await client.post("/admin/users", json=payload, headers=headers)
    assert r1.status_code == 201
    r2 = await client.post("/admin/users", json=payload, headers=headers)
    assert r2.status_code == 409


async def test_editar_nome_e_toggle_ativo(
    client: AsyncClient, admin_user: User, accounting_firm: AccountingFirm,
) -> None:
    headers = auth_headers(admin_user)
    r = await client.post(
        "/admin/users",
        json={
            "email": "operador@teste.com.br", "password": "Senha@123",
            "full_name": "Operador Original", "role": "OPERADOR",
            "accounting_firm_id": accounting_firm.id,
        },
        headers=headers,
    )
    user_id = r.json()["id"]

    r = await client.patch(
        f"/admin/users/{user_id}", json={"full_name": "Operador Editado"}, headers=headers,
    )
    assert r.status_code == 200
    assert r.json()["full_name"] == "Operador Editado"

    r = await client.patch(f"/admin/users/{user_id}", json={"is_active": False}, headers=headers)
    assert r.status_code == 200
    assert r.json()["is_active"] is False


# ── Stats ────────────────────────────────────────────────────────────────────

async def test_stats_reflete_escritorio_criado(client: AsyncClient, admin_user: User) -> None:
    headers = auth_headers(admin_user)
    r_before = await client.get("/admin/stats", headers=headers)
    before = r_before.json()["total_accounting_firms"]

    await _create_firm(client, headers)

    r_after = await client.get("/admin/stats", headers=headers)
    after = r_after.json()
    assert after["total_accounting_firms"] == before + 1
    assert set(after.keys()) == {
        "total_accounting_firms", "active_subscriptions", "total_jobs_processed", "failed_jobs",
    }


# ── Autorização ──────────────────────────────────────────────────────────────

async def test_gestor_recebe_403_em_rota_admin(client: AsyncClient, gestor_user: User) -> None:
    headers = auth_headers(gestor_user)
    r = await client.get("/admin/stats", headers=headers)
    assert r.status_code == 403
