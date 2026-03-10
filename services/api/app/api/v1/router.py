from fastapi import APIRouter

from app.api.v1 import puzzles, admin

router = APIRouter(prefix="/api/v1")

router.include_router(puzzles.router)
router.include_router(admin.router)
