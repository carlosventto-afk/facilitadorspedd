"""Testes do fluxo de autenticação: login, refresh e redefinição de senha."""
from __future__ import annotations

from datetime import timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import (
    _create_token,
    create_access_token,
    create_invite_token,
    create_password_reset_token,
    hash_password,
)
from app.db.models import AccountingFirm, Invitation, InvitationStatus, User, UserRole


async def test_login_com_credenciais_validas(client: AsyncClient, gestor_user: User) -> None:
    r = await client.post(
        "/auth/login", json={"email": "gestor@teste.com.br", "password": "Senha@123"}
    )
    assert r.status_code == 200
    assert r.json()["access_token"]


# ── Esqueci minha senha ─────────────────────────────────────────────────────

async def test_forgot_password_email_existente_dispara_email_e_retorna_204(
    client: AsyncClient, gestor_user: User, monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent: list[dict] = []

    async def _fake_send_email(to: str, subject: str, html_content: str) -> None:
        sent.append({"to": to, "subject": subject, "html_content": html_content})

    monkeypatch.setattr("app.api.v1.routes.auth.send_email", _fake_send_email)

    r = await client.post("/auth/forgot-password", json={"email": "gestor@teste.com.br"})
    assert r.status_code == 204
    assert len(sent) == 1
    assert sent[0]["to"] == "gestor@teste.com.br"
    assert "reset-password?token=" in sent[0]["html_content"]


async def test_forgot_password_email_inexistente_tambem_retorna_204_sem_enviar(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regressão de enumeração de usuário: resposta não pode diferenciar
    e-mail cadastrado de não cadastrado."""
    sent: list[dict] = []

    async def _fake_send_email(to: str, subject: str, html_content: str) -> None:
        sent.append({"to": to})

    monkeypatch.setattr("app.api.v1.routes.auth.send_email", _fake_send_email)

    r = await client.post("/auth/forgot-password", json={"email": "naoexiste@teste.com.br"})
    assert r.status_code == 204
    assert sent == []


# ── Redefinir senha ──────────────────────────────────────────────────────────

async def test_reset_password_com_token_valido_troca_senha(
    client: AsyncClient, gestor_user: User,
) -> None:
    token = create_password_reset_token(gestor_user.id)
    r = await client.post(
        "/auth/reset-password", json={"token": token, "new_password": "NovaSenha@456"}
    )
    assert r.status_code == 204

    # senha antiga não funciona mais
    r_old = await client.post(
        "/auth/login", json={"email": "gestor@teste.com.br", "password": "Senha@123"}
    )
    assert r_old.status_code == 401

    # senha nova funciona
    r_new = await client.post(
        "/auth/login", json={"email": "gestor@teste.com.br", "password": "NovaSenha@456"}
    )
    assert r_new.status_code == 200


async def test_reset_password_token_invalido_retorna_400(client: AsyncClient) -> None:
    r = await client.post(
        "/auth/reset-password", json={"token": "token-invalido", "new_password": "NovaSenha@456"}
    )
    assert r.status_code == 400


async def test_reset_password_com_access_token_normal_e_rejeitado(
    client: AsyncClient, gestor_user: User,
) -> None:
    """Token de acesso normal (login) não pode ser reaproveitado para reset
    de senha — só um token com type=password_reset é aceito."""
    access_token = create_access_token(gestor_user.id, gestor_user.role.value)
    r = await client.post(
        "/auth/reset-password", json={"token": access_token, "new_password": "NovaSenha@456"}
    )
    assert r.status_code == 400


async def test_reset_password_usuario_inativo_e_rejeitado(
    client: AsyncClient, gestor_user: User, db: AsyncSession,
) -> None:
    gestor_user.is_active = False
    db.add(gestor_user)
    await db.commit()

    token = create_password_reset_token(gestor_user.id)
    r = await client.post(
        "/auth/reset-password", json={"token": token, "new_password": "NovaSenha@456"}
    )
    assert r.status_code == 400


# ── Aceitar convite ──────────────────────────────────────────────────────────

async def test_accept_invite_com_token_valido_cria_usuario_gestor(
    client: AsyncClient, db: AsyncSession, pending_invitation: Invitation,
    accounting_firm: AccountingFirm,
) -> None:
    token = create_invite_token(pending_invitation.id)
    r = await client.post(
        "/auth/accept-invite",
        json={"token": token, "full_name": "Convidado Aceito", "password": "SenhaForte@789"},
    )
    assert r.status_code == 204

    r_login = await client.post(
        "/auth/login",
        json={"email": pending_invitation.email, "password": "SenhaForte@789"},
    )
    assert r_login.status_code == 200

    r_me = await client.get(
        "/auth/me", headers={"Authorization": f"Bearer {r_login.json()['access_token']}"}
    )
    assert r_me.json()["role"] == "GESTOR"
    assert r_me.json()["accounting_firm_id"] == accounting_firm.id

    await db.refresh(pending_invitation)
    assert pending_invitation.status == InvitationStatus.ACCEPTED
    assert pending_invitation.created_user_id is not None


async def test_accept_invite_token_invalido_retorna_400(client: AsyncClient) -> None:
    r = await client.post(
        "/auth/accept-invite",
        json={"token": "token-invalido", "full_name": "X", "password": "SenhaForte@789"},
    )
    assert r.status_code == 400


async def test_accept_invite_token_type_errado_e_rejeitado(
    client: AsyncClient, gestor_user: User,
) -> None:
    token = create_password_reset_token(gestor_user.id)
    r = await client.post(
        "/auth/accept-invite",
        json={"token": token, "full_name": "X", "password": "SenhaForte@789"},
    )
    assert r.status_code == 400


async def test_accept_invite_token_expirado_retorna_400(
    client: AsyncClient, pending_invitation: Invitation,
) -> None:
    token = _create_token(
        pending_invitation.id, timedelta(minutes=-1), extra={"type": "invite"}
    )
    r = await client.post(
        "/auth/accept-invite",
        json={"token": token, "full_name": "X", "password": "SenhaForte@789"},
    )
    assert r.status_code == 400


async def test_accept_invite_convite_ja_aceito_retorna_400(
    client: AsyncClient, pending_invitation: Invitation,
) -> None:
    token = create_invite_token(pending_invitation.id)
    r1 = await client.post(
        "/auth/accept-invite",
        json={"token": token, "full_name": "X", "password": "SenhaForte@789"},
    )
    assert r1.status_code == 204

    r2 = await client.post(
        "/auth/accept-invite",
        json={"token": token, "full_name": "Y", "password": "OutraSenha@123"},
    )
    assert r2.status_code == 400


async def test_accept_invite_convite_cancelado_retorna_400(
    client: AsyncClient, db: AsyncSession, pending_invitation: Invitation,
) -> None:
    pending_invitation.status = InvitationStatus.CANCELED
    await db.commit()

    token = create_invite_token(pending_invitation.id)
    r = await client.post(
        "/auth/accept-invite",
        json={"token": token, "full_name": "X", "password": "SenhaForte@789"},
    )
    assert r.status_code == 400


async def test_accept_invite_email_ja_cadastrado_retorna_409(
    client: AsyncClient, db: AsyncSession, pending_invitation: Invitation,
) -> None:
    db.add(User(
        email=pending_invitation.email,
        password_hash=hash_password("Outra@123"),
        full_name="Já Existe",
        role=UserRole.GESTOR,
        accounting_firm_id=pending_invitation.accounting_firm_id,
    ))
    await db.commit()

    token = create_invite_token(pending_invitation.id)
    r = await client.post(
        "/auth/accept-invite",
        json={"token": token, "full_name": "X", "password": "SenhaForte@789"},
    )
    assert r.status_code == 409
