"""
RGPD / GDPR helpers.

- pseudonymize(): irreversible-without-salt, deterministic pseudonymisation of a
  commenter handle (Art. 4(5) GDPR). Same handle -> same pseudonym, so analytics
  (e.g. recurring commenters) stay meaningful while the real identity is hidden.
- erase_subject(): right to erasure (Art. 17) — delete every comment of a person.
- purge_old_comments(): storage limitation (Art. 5(1)(e)) — retention cleanup.
"""
import hashlib
import hmac
import re
from datetime import datetime, timedelta, timezone

from app.config import settings

_PSEUDO_RE = re.compile(r"^u_[0-9a-f]{12}$")


def pseudonymize(username: str) -> str:
    """Deterministic HMAC-SHA256 pseudonym of a social handle. Idempotent."""
    if not username:
        return "anonymous"
    handle = username.strip().lstrip("@").lower()
    if not handle:
        return "anonymous"
    if _PSEUDO_RE.match(handle):       # already pseudonymised — keep stable
        return handle
    salt = (settings.PSEUDONYM_SALT or "sentinelle").encode("utf-8")
    digest = hmac.new(salt, handle.encode("utf-8"), hashlib.sha256).hexdigest()
    return "u_" + digest[:12]


def is_pseudonym(value: str) -> bool:
    return bool(_PSEUDO_RE.match((value or "").strip()))


# ── Right to erasure (Art. 17) ────────────────────────────────────────────────

def erase_subject(db, username: str) -> int:
    """Delete every comment authored by `username` (matched on its pseudonym).
    `db` is a sync SQLAlchemy session. Returns the number of rows removed."""
    from app.models.comment import Comment
    pseudo = pseudonymize(username)
    rows = db.query(Comment).filter(Comment.author == pseudo).delete(synchronize_session=False)
    db.commit()
    return rows


# ── Storage limitation / retention (Art. 5(1)(e)) ─────────────────────────────

def purge_old_comments(db, days: int | None = None) -> int:
    """Delete comments older than `days` (default COMMENT_RETENTION_DAYS)."""
    from app.models.comment import Comment
    days = days or settings.COMMENT_RETENTION_DAYS
    cutoff = datetime.utcnow() - timedelta(days=days)
    rows = (
        db.query(Comment)
        .filter(Comment.scraped_at < cutoff)
        .delete(synchronize_session=False)
    )
    db.commit()
    return rows
