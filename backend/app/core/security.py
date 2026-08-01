"""
Authentication core: password hashing (bcrypt) + JWT issuing/verification (python-jose).

The dependency `get_current_user` protects every secured route: it reads the
`Authorization: Bearer <token>` header, validates the signature and expiry, and
loads the matching active user from the database.
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import jwt, JWTError
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models.user import User

logger = logging.getLogger(__name__)

# tokenUrl lets Swagger UI's "Authorize" button know where to get a token.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/auth/login", auto_error=True)


# ── Password hashing (bcrypt directly — avoids passlib/bcrypt version clashes) ──

def hash_password(password: str) -> str:
    # bcrypt only uses the first 72 bytes; truncate to stay within the limit.
    pw = password.encode("utf-8")[:72]
    return bcrypt.hashpw(pw, bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8")[:72], hashed.encode("utf-8"))
    except Exception:
        return False


# ── JWT ───────────────────────────────────────────────────────────────────────

def create_access_token(subject: str, extra: Optional[dict] = None) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": subject,
        "iat": now,
        "exp": now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
    }
    if extra:
        payload.update(extra)
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    cred_exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Session invalide ou expirée — veuillez vous reconnecter",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        email = payload.get("sub")
        if not email:
            raise cred_exc
    except JWTError:
        raise cred_exc

    user = (await db.scalars(select(User).where(User.email == email))).first()
    if not user or not user.is_active:
        raise cred_exc
    return user


# ── Default admin seeding ─────────────────────────────────────────────────────

async def ensure_default_admin() -> None:
    """Create the first admin account from env vars if the users table is empty."""
    from app.database import AsyncSessionLocal
    async with AsyncSessionLocal() as db:
        count = (await db.scalar(select(func.count()).select_from(User))) or 0
        if count > 0:
            return
        admin = User(
            email=settings.ADMIN_EMAIL.lower(),
            full_name="Administrateur Media Net",
            hashed_password=hash_password(settings.ADMIN_PASSWORD),
            role="admin",
        )
        db.add(admin)
        await db.commit()
        logger.info("Seeded default admin account: %s", settings.ADMIN_EMAIL)
