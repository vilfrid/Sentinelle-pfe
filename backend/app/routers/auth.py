from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User
from app.schemas.auth import LoginRequest, Token, UserOut, UserCreate
from app.core.security import (
    verify_password, hash_password, create_access_token, get_current_user,
)

router = APIRouter()


@router.post("/login", response_model=Token)
async def login(payload: LoginRequest, db: AsyncSession = Depends(get_db)):
    """Authenticate with email + password and receive a signed JWT."""
    email = payload.email.strip().lower()
    user = (await db.scalars(select(User).where(User.email == email))).first()
    if not user or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Email ou mot de passe incorrect"
        )
    if not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Ce compte est désactivé")

    user.last_login = datetime.utcnow()
    await db.commit()

    token = create_access_token(
        subject=user.email,
        extra={"role": user.role, "name": user.full_name or ""},
    )
    return Token(access_token=token)


@router.get("/me", response_model=UserOut)
async def me(current: User = Depends(get_current_user)):
    """Return the currently authenticated user (used by the frontend to rehydrate)."""
    return current


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def register(
    payload: UserCreate,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Create a new user. Restricted to admins."""
    if current.role != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Réservé aux administrateurs")

    email = payload.email.strip().lower()
    existing = (await db.scalars(select(User).where(User.email == email))).first()
    if existing:
        raise HTTPException(status.HTTP_409_CONFLICT, "Un compte existe déjà avec cet email")

    user = User(
        email=email,
        full_name=payload.full_name,
        hashed_password=hash_password(payload.password),
        role=payload.role if payload.role in ("admin", "manager") else "manager",
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user
