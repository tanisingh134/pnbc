from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.core.security import create_access_token
from app.models.user import User
from app.schemas.auth import Token, UserLogin, UserRegister, UserResponse
from app.services.auth_service import AuthService

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def register(user_in: UserRegister, db: Session = Depends(get_db)) -> UserResponse:
    """Register a new user with email and password."""
    user = AuthService.register_user(db, user_in)
    return user


@router.post("/login", response_model=Token, status_code=status.HTTP_200_OK)
def login(login_in: UserLogin, db: Session = Depends(get_db)) -> Token:
    """Authenticate with email and password to obtain a JWT Bearer token."""
    user = AuthService.authenticate_user(db, login_in.email, login_in.password)
    access_token = create_access_token(
        subject=str(user.id),
        claims={"email": user.email},
    )
    return Token(access_token=access_token, token_type="bearer")


@router.get("/me", response_model=UserResponse, status_code=status.HTTP_200_OK)
def get_current_user_profile(current_user: User = Depends(get_current_user)) -> UserResponse:
    """Get the authenticated user's profile."""
    return current_user
