import uuid
from typing import Generator
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import UnauthorizedException
from app.core.security import decode_access_token
from app.db.session import get_db
from app.models.user import User
from app.services.auth_service import AuthService
from app.services.storage.base import BaseStorageService
from app.services.storage.local import LocalStorageService

security = HTTPBearer(auto_error=False)


def get_storage_service() -> BaseStorageService:
    """Dependency provider for storage service abstraction."""
    return LocalStorageService(settings.UPLOAD_DIR)


def get_current_user(
    auth_creds: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db),
) -> User:
    """Dependency to extract, decode, and authenticate user from Bearer JWT token."""
    if not auth_creds or not auth_creds.credentials:
        raise UnauthorizedException("Authorization header missing or invalid format")

    payload = decode_access_token(auth_creds.credentials)
    if not payload:
        raise UnauthorizedException("Invalid or expired authentication token")

    user_id_str = payload.get("sub")
    if not user_id_str:
        raise UnauthorizedException("Token payload missing subject identifier")

    try:
        user_id = uuid.UUID(user_id_str)
    except ValueError:
        raise UnauthorizedException("Invalid subject identifier in token")

    user = AuthService.get_user_by_id(db, user_id)
    if not user:
        raise UnauthorizedException("User associated with token no longer exists")

    return user
