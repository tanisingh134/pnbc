from fastapi import APIRouter
from app.api.v1.auth import router as auth_router
from app.api.v1.document_groups import router as document_groups_router
from app.api.v1.documents import router as documents_router
from app.api.v1.questions import router as questions_router

api_router = APIRouter()

api_router.include_router(auth_router)
api_router.include_router(documents_router)
api_router.include_router(document_groups_router)
api_router.include_router(questions_router)
