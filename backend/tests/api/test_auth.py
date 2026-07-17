"""Testes do fluxo de autenticação: login, refresh e redefinição de senha."""
from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, create_password_reset_token
from app.db.models import User


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
