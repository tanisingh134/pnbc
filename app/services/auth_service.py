import uuid
from typing import Optional
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import ConflictException, UnauthorizedException
from app.core.security import hash_password, verify_password
from app.models.user import User
from app.schemas.auth import UserRegister


class AuthService:
    @staticmethod
    def register_user(db: Session, user_in: UserRegister) -> User:
        """Register a new user with unique email check and bcrypt password hash."""
        existing_user = db.scalar(select(User).where(User.email == user_in.email.lower()))
        if existing_user:
            raise ConflictException("A user with this email address already exists")

        user = User(
            email=user_in.email.lower(),
            password_hash=hash_password(user_in.password),
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user

    @staticmethod
    def authenticate_user(db: Session, email: str, password: str) -> User:
        """Authenticate user credentials."""
        user = db.scalar(select(User).where(User.email == email.lower()))
        if not user or not verify_password(password, user.password_hash):
            raise UnauthorizedException("Invalid email or password")
        return user

    @staticmethod
    def get_user_by_id(db: Session, user_id: uuid.UUID) -> Optional[User]:
        """Fetch user by primary key ID."""
        return db.get(User, user_id)
