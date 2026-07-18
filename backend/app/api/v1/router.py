from fastapi import APIRouter

from app.api.v1.endpoints import download, extract

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(extract.router, tags=["extract"])
api_router.include_router(download.router, tags=["download"])
