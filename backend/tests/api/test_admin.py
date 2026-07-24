"""Testes das rotas /admin/* (só role ADMIN)."""
from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AccountingFirm, Company, Invitation, InvitationStatus, User

from .conftest import auth_headers


async def _create_firm(
    client: AsyncClient, headers: dict, cpf_cnpj: str = "33444555000166"
) -> dict:
    r = await client.post(
        "/admin/accounting-firms",
        json={
            "name": "Escritório Novo LTDA", "cpf_cnpj": cpf_cnpj, "email": "novo@escritorio.com.br",
        },
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
    await _create_firm(client, headers, cpf_cnpj="11222333000181")
    r = await client.post(
        "/admin/accounting-firms",
        json={"name": "Outro", "cpf_cnpj": "11222333000181", "email": "outro@teste.com.br"},
        headers=headers,
    )
    assert r.status_code == 409


async def test_admin_cria_escritorio_com_cpf(client: AsyncClient, admin_user: User) -> None:
    headers = auth_headers(admin_user)
    firm = await _create_firm(client, headers, cpf_cnpj="529.982.247-25")
    assert firm["cpf_cnpj"] == "52998224725"


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


# ── Convites ─────────────────────────────────────────────────────────────────

async def test_criar_convite_e_listar(
    client: AsyncClient, admin_user: User, accounting_firm: AccountingFirm,
) -> None:
    headers = auth_headers(admin_user)
    r = await client.post(
        "/admin/invitations",
        json={"email": "convidado@teste.com.br", "accounting_firm_id": accounting_firm.id},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["status"] == "PENDING"
    assert data["accounting_firm_id"] == accounting_firm.id
    assert data["invited_by"] == admin_user.id

    r = await client.get("/admin/invitations", headers=headers)
    assert r.status_code == 200
    emails = [i["email"] for i in r.json()]
    assert "convidado@teste.com.br" in emails


async def test_criar_convite_escritorio_inexistente_retorna_404(
    client: AsyncClient, admin_user: User,
) -> None:
    headers = auth_headers(admin_user)
    r = await client.post(
        "/admin/invitations",
        json={"email": "x@teste.com.br", "accounting_firm_id": "id-que-nao-existe"},
        headers=headers,
    )
    assert r.status_code == 404


async def test_criar_convite_email_ja_cadastrado_retorna_409(
    client: AsyncClient, admin_user: User, accounting_firm: AccountingFirm, gestor_user: User,
) -> None:
    headers = auth_headers(admin_user)
    r = await client.post(
        "/admin/invitations",
        json={"email": gestor_user.email, "accounting_firm_id": accounting_firm.id},
        headers=headers,
    )
    assert r.status_code == 409


async def test_criar_convite_duplicado_pendente_retorna_409(
    client: AsyncClient, admin_user: User, accounting_firm: AccountingFirm,
) -> None:
    headers = auth_headers(admin_user)
    payload = {"email": "duplicado.convite@teste.com.br", "accounting_firm_id": accounting_firm.id}
    r1 = await client.post("/admin/invitations", json=payload, headers=headers)
    assert r1.status_code == 201
    r2 = await client.post("/admin/invitations", json=payload, headers=headers)
    assert r2.status_code == 409


async def test_criar_convite_dispara_email_com_link(
    client: AsyncClient, admin_user: User, accounting_firm: AccountingFirm,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent: list[dict] = []

    async def _fake_send_email(to: str, subject: str, html_content: str) -> None:
        sent.append({"to": to, "html_content": html_content})

    monkeypatch.setattr("app.api.v1.routes.admin.send_email", _fake_send_email)

    r = await client.post(
        "/admin/invitations",
        json={"email": "novo.convite@teste.com.br", "accounting_firm_id": accounting_firm.id},
        headers=auth_headers(admin_user),
    )
    assert r.status_code == 201
    assert len(sent) == 1
    assert sent[0]["to"] == "novo.convite@teste.com.br"
    assert "accept-invite?token=" in sent[0]["html_content"]


async def test_cancelar_convite_pendente(
    client: AsyncClient, admin_user: User, pending_invitation: Invitation,
) -> None:
    headers = auth_headers(admin_user)
    r = await client.delete(f"/admin/invitations/{pending_invitation.id}", headers=headers)
    assert r.status_code == 204

    r = await client.get("/admin/invitations", headers=headers)
    canceled = [i for i in r.json() if i["id"] == pending_invitation.id]
    assert canceled[0]["status"] == "CANCELED"


async def test_cancelar_convite_ja_aceito_retorna_400(
    client: AsyncClient, admin_user: User, db: AsyncSession, pending_invitation: Invitation,
) -> None:
    pending_invitation.status = InvitationStatus.ACCEPTED
    await db.commit()

    r = await client.delete(
        f"/admin/invitations/{pending_invitation.id}", headers=auth_headers(admin_user),
    )
    assert r.status_code == 400


async def test_cancelar_convite_inexistente_retorna_404(
    client: AsyncClient, admin_user: User,
) -> None:
    r = await client.delete(
        "/admin/invitations/id-que-nao-existe", headers=auth_headers(admin_user),
    )
    assert r.status_code == 404


# ── Empresas (visão cross-firm) ──────────────────────────────────────────────

async def test_criar_empresa_para_escritorio_especifico(
    client: AsyncClient, admin_user: User, accounting_firm: AccountingFirm,
) -> None:
    headers = auth_headers(admin_user)
    r = await client.post(
        "/admin/companies",
        json={
            "name": "Empresa Via Admin LTDA",
            "cnpj": "55666777000188",
            "uf": "PA",
            "accounting_firm_id": accounting_firm.id,
        },
        headers=headers,
    )
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["accounting_firm_id"] == accounting_firm.id
    assert data["is_active"] is True


async def test_criar_empresa_escritorio_inexistente_retorna_404(
    client: AsyncClient, admin_user: User,
) -> None:
    headers = auth_headers(admin_user)
    r = await client.post(
        "/admin/companies",
        json={
            "name": "Empresa Órfã",
            "cnpj": "11111111000191",
            "uf": "PA",
            "accounting_firm_id": "id-que-nao-existe",
        },
        headers=headers,
    )
    assert r.status_code == 404


async def test_criar_empresa_cnpj_duplicado_no_mesmo_escritorio_retorna_409(
    client: AsyncClient, admin_user: User, accounting_firm: AccountingFirm,
) -> None:
    headers = auth_headers(admin_user)
    payload = {
        "name": "Empresa X", "cnpj": "99888777000166", "uf": "PA",
        "accounting_firm_id": accounting_firm.id,
    }
    r1 = await client.post("/admin/companies", json=payload, headers=headers)
    assert r1.status_code == 201
    r2 = await client.post("/admin/companies", json=payload, headers=headers)
    assert r2.status_code == 409


async def test_listar_empresas_de_todos_os_escritorios(
    client: AsyncClient, admin_user: User, accounting_firm: AccountingFirm, company: Company,
) -> None:
    headers = auth_headers(admin_user)
    firm2 = await _create_firm(client, headers, cpf_cnpj="22111222000133")
    r = await client.post(
        "/admin/companies",
        json={
            "name": "Empresa do Segundo Escritório",
            "cnpj": "33222111000144",
            "uf": "PA",
            "accounting_firm_id": firm2["id"],
        },
        headers=headers,
    )
    assert r.status_code == 201

    r = await client.get("/admin/companies", headers=headers)
    assert r.status_code == 200
    firm_ids = {c["accounting_firm_id"] for c in r.json()}
    assert accounting_firm.id in firm_ids
    assert firm2["id"] in firm_ids


async def test_editar_empresa_via_admin(
    client: AsyncClient, admin_user: User, company: Company,
) -> None:
    headers = auth_headers(admin_user)
    r = await client.patch(
        f"/admin/companies/{company.id}", json={"name": "Nome Atualizado"}, headers=headers,
    )
    assert r.status_code == 200
    assert r.json()["name"] == "Nome Atualizado"


async def test_toggle_ativo_empresa_via_admin(
    client: AsyncClient, admin_user: User, company: Company,
) -> None:
    headers = auth_headers(admin_user)
    r = await client.patch(
        f"/admin/companies/{company.id}", json={"is_active": False}, headers=headers,
    )
    assert r.status_code == 200
    assert r.json()["is_active"] is False


async def test_editar_empresa_inexistente_retorna_404(
    client: AsyncClient, admin_user: User,
) -> None:
    headers = auth_headers(admin_user)
    r = await client.patch(
        "/admin/companies/id-que-nao-existe", json={"name": "X"}, headers=headers,
    )
    assert r.status_code == 404


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

    r = await client.get("/admin/companies", headers=headers)
    assert r.status_code == 403

    r = await client.get("/admin/invitations", headers=headers)
    assert r.status_code == 403
