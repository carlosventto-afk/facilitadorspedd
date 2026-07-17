from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.schemas.auth import (
    AccessTokenResponse,
    LoginRequest,
    PasswordResetConfirm,
    PasswordResetRequest,
    RefreshRequest,
    TokenResponse,
    UserProfile,
)
from app.core.config import settings
from app.core.deps import CurrentUser
from app.core.email import send_email
from app.core.security import (
    create_access_token,
    create_password_reset_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.db.models import User
from app.db.session import get_db

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
async def login(
    payload: LoginRequest,
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TokenResponse:
    result = await db.execute(select(User).where(User.email == payload.email.lower()))
    user = result.scalar_one_or_none()

    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Credenciais inválidas")

    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Usuário inativo")

    access_token = create_access_token(user.id, user.role.value)
    refresh_token = create_refresh_token(user.id)

    # Store refresh token in HttpOnly cookie as well
    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=30 * 24 * 60 * 60,
    )

    return TokenResponse(access_token=access_token, refresh_token=refresh_token)


@router.post("/refresh", response_model=AccessTokenResponse)
async def refresh_token(
    payload: RefreshRequest | None = None,
    refresh_token_cookie: str | None = Cookie(default=None, alias="refresh_token"),
    db: AsyncSession = Depends(get_db),
) -> AccessTokenResponse:
    token = (payload.refresh_token if payload else None) or refresh_token_cookie
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token ausente")

    try:
        data = decode_token(token)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token inválido")

    if data.get("type") != "refresh":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token inválido")

    result = await db.execute(select(User).where(User.id == data["sub"]))
    user = result.scalar_one_or_none()

    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Usuário não encontrado")

    return AccessTokenResponse(access_token=create_access_token(user.id, user.role.value))


@router.post("/logout")
async def logout(response: Response) -> dict:
    response.delete_cookie("refresh_token")
    return {"message": "Logout realizado com sucesso"}


@router.get("/me", response_model=UserProfile)
async def me(current_user: CurrentUser) -> UserProfile:
    return UserProfile.model_validate(current_user)


@router.post("/forgot-password", status_code=status.HTTP_204_NO_CONTENT)
async def forgot_password(
    payload: PasswordResetRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    """Envia um e-mail com link de redefinição de senha, se o e-mail existir.

    Sempre retorna 204, exista ou não o e-mail — evita que a resposta seja
    usada para descobrir quais e-mails estão cadastrados (enumeração de
    usuário)."""
    result = await db.execute(select(User).where(User.email == payload.email.lower()))
    user = result.scalar_one_or_none()

    if user and user.is_active:
        token = create_password_reset_token(user.id)
        reset_link = f"{settings.FRONTEND_URL}/reset-password?token={token}"
        await send_email(
            to=user.email,
            subject="Redefinição de senha — FacilitadorSped",
            html_content=(
                f"<p>Olá, {user.full_name}.</p>"
                f"<p>Recebemos um pedido para redefinir sua senha. "
                f"Esse link expira em {settings.PASSWORD_RESET_TOKEN_EXPIRE_MINUTES} minutos:</p>"
                f'<p><a href="{reset_link}">{reset_link}</a></p>'
                f"<p>Se você não pediu isso, pode ignorar este e-mail.</p>"
            ),
        )


@router.post("/reset-password", status_code=status.HTTP_204_NO_CONTENT)
async def reset_password(
    payload: PasswordResetConfirm,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    try:
        data = decode_token(payload.token)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Link inválido ou expirado"
        )

    if data.get("type") != "password_reset":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Link inválido")

    result = await db.execute(select(User).where(User.id == data.get("sub")))
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Link inválido ou expirado"
        )

    user.password_hash = hash_password(payload.new_password)
    await db.commit()
