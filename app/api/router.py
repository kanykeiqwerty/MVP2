from fastapi import APIRouter

from app.api.endpoints import admin, auth, dialog, document, profile


router = APIRouter(prefix="/api/v1")
router.include_router(document.router)
router.include_router(dialog.router)
router.include_router(auth.router)
router.include_router(admin.router)
router.include_router(profile.router)