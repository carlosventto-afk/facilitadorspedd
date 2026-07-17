"""Fixtures compartilhadas para os testes de API (app FastAPI + banco de teste)."""
from __future__ import annotations

from collections.abc import AsyncGenerator
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.core.security import create_access_token, hash_password
from app.db.base import Base
from app.db.models import AccountingFirm, Company, User, UserRole
from app.db.session import get_db
from app.main import app


@pytest_asyncio.fixture
async def session_factory(tmp_path: Path) -> AsyncGenerator[async_sessionmaker[AsyncSession], None]:
    """SQLite em arquivo (não :memory:) — API e chamadas diretas à task
    precisam enxergar o MESMO banco através de conexões/sessões diferentes,
    o que :memory: não garante (cada conexão abriria seu próprio banco vazio)."""
    db_path = tmp_path / "test.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    try:
        yield factory
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def db(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncGenerator[AsyncSession, None]:
    """Sessão avulsa para inserir dados de setup direto via ORM (sem HTTP)."""
    async with session_factory() as session:
        yield session


@pytest.fixture(autouse=True)
def _local_storage_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Isola cada teste num diretório de storage próprio, sem tocar backend/data/ real."""
    storage_dir = tmp_path / "uploads"
    monkeypatch.setattr(settings, "LOCAL_STORAGE_DIR", storage_dir)
    return storage_dir


@pytest_asyncio.fixture
async def client(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncGenerator[AsyncClient, None]:
    async def _override_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = _override_get_db
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://testserver/api/v1") as ac:
            yield ac
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest_asyncio.fixture
async def accounting_firm(db: AsyncSession) -> AccountingFirm:
    firm = AccountingFirm(
        name="Escritório Teste", cnpj="11222333000181", email="contato@teste.com.br"
    )
    db.add(firm)
    await db.commit()
    await db.refresh(firm)
    return firm


@pytest_asyncio.fixture
async def gestor_user(db: AsyncSession, accounting_firm: AccountingFirm) -> User:
    user = User(
        email="gestor@teste.com.br",
        password_hash=hash_password("Senha@123"),
        full_name="Gestor Teste",
        role=UserRole.GESTOR,
        accounting_firm_id=accounting_firm.id,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


@pytest_asyncio.fixture
async def company(db: AsyncSession, accounting_firm: AccountingFirm) -> Company:
    comp = Company(
        accounting_firm_id=accounting_firm.id,
        name="Empresa Teste LTDA",
        cnpj="22333444000199",
        uf="PA",
    )
    db.add(comp)
    await db.commit()
    await db.refresh(comp)
    return comp


def auth_headers(user: User) -> dict[str, str]:
    token = create_access_token(user.id, user.role.value)
    return {"Authorization": f"Bearer {token}"}
