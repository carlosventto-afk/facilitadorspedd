from fastapi import APIRouter

from app.api.v1.routes import admin, auth, firms, jobs

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(admin.router)
api_router.include_router(firms.router)
api_router.include_router(jobs.router)
