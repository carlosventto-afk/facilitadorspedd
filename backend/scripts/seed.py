"""
Cria o usuário ADMIN inicial para primeiro acesso ao sistema.
Uso: python -m scripts.seed
     ou via docker: docker-compose exec backend python -m scripts.seed
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.core.security import hash_password
from app.db.models import User, UserRole

ADMIN_EMAIL = os.getenv("SEED_ADMIN_EMAIL", "admin@facilitadorsped.com.br")
ADMIN_PASSWORD = os.getenv("SEED_ADMIN_PASSWORD", "Admin@123")
ADMIN_NAME = os.getenv("SEED_ADMIN_NAME", "Administrador")


async def seed() -> None:
    engine = create_async_engine(settings.DATABASE_URL)
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async with SessionLocal() as db:
        existing = await db.execute(select(User).where(User.email == ADMIN_EMAIL))
        if existing.scalar_one_or_none():
            print(f"[seed] Usuário admin já existe: {ADMIN_EMAIL}")
            return

        admin = User(
            email=ADMIN_EMAIL,
            password_hash=hash_password(ADMIN_PASSWORD),
            full_name=ADMIN_NAME,
            role=UserRole.ADMIN,
            is_active=True,
        )
        db.add(admin)
        await db.commit()
        print(f"[seed] Usuário admin criado: {ADMIN_EMAIL} / senha: {ADMIN_PASSWORD}")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(seed())
