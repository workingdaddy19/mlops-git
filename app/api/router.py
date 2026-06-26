from fastapi import APIRouter

from app.api.routes import access_log, auth, board, jupyter, permissions, query, resource, s3_storage
from app.api.routes.admin import router as admin_router

api_router = APIRouter(prefix="/api")
api_router.include_router(auth.router)
api_router.include_router(access_log.router)
api_router.include_router(board.router)
api_router.include_router(query.router)
api_router.include_router(jupyter.router)
api_router.include_router(s3_storage.router)
api_router.include_router(permissions.router)
api_router.include_router(permissions.admin_router)
api_router.include_router(resource.router)
api_router.include_router(admin_router)
