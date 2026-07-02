from fastapi import APIRouter

from app.api.endpoints import dialog, document


router = APIRouter(prefix="/api/v1")
router.include_router(document.router)
router.include_router(dialog.router)