from fastapi import APIRouter

from app.api.endpoints import document


router = APIRouter(prefix="/api/v1")
router.include_router(document.router)