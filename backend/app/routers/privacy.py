"""RGPD / GDPR endpoints: erasure (Art. 17), retention purge (Art. 5(1)(e)), info."""
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.config import settings
from app.database import get_sync_db
from app.core.security import get_current_user
from app.core.privacy import erase_subject, purge_old_comments
from app.models.user import User

router = APIRouter()


class EraseRequest(BaseModel):
    username: str


def _require_admin(current: User):
    if current.role != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Réservé aux administrateurs")


@router.get("/policy")
async def policy(current: User = Depends(get_current_user)):
    """Expose the data-protection posture (basis, pseudonymisation, retention)."""
    return {
        "lawful_basis": "legitimate interest (brand sentiment analytics)",
        "pseudonymisation": "comment authors are pseudonymised (HMAC-SHA256) at ingestion",
        "retention_days": settings.COMMENT_RETENTION_DAYS,
        "data_subject_rights": ["access", "rectification", "erasure", "objection"],
    }


@router.post("/erase")
async def erase(payload: EraseRequest, current: User = Depends(get_current_user)):
    """Right to erasure: delete every comment of a given handle (Art. 17)."""
    _require_admin(current)
    db = get_sync_db()
    try:
        removed = erase_subject(db, payload.username)
    finally:
        db.close()
    return {"erased_comments": removed, "username": payload.username}


@router.post("/purge")
async def purge(days: int | None = None, current: User = Depends(get_current_user)):
    """Storage-limitation purge of comments older than `days` (Art. 5(1)(e))."""
    _require_admin(current)
    db = get_sync_db()
    try:
        removed = purge_old_comments(db, days)
    finally:
        db.close()
    return {"purged_comments": removed, "older_than_days": days or settings.COMMENT_RETENTION_DAYS}
