"""Extracts comment data from Instagram JSONL files (private API format).

Real API shape per record (data field):
  pk                    → external_id
  text                  → raw_text
  created_at            → posted_at (Unix timestamp)
  comment_like_count    → likes
  child_comment_count   → reply_count
  is_liked_by_media_owner → liked by the creator (quality signal)
  user.username         → author
  user.full_name        → author_display_name
  user.is_verified      → author_verified
  user.pk               → author_id
"""
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict

logger = logging.getLogger(__name__)


def _ts(unix: int | None) -> datetime | None:
    if not unix:
        return None
    try:
        return datetime.fromtimestamp(int(unix), tz=timezone.utc)
    except (TypeError, ValueError, OSError):
        return None


class InstagramCleaner:
    def extract_comments(self, jsonl_path: Path) -> List[Dict]:
        comments = []
        with open(jsonl_path, encoding="utf-8") as f:
            for i, line in enumerate(f):
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                    c = record.get("data", record)
                    text = c.get("text", "").replace("\n", " ").strip()
                    if not text:
                        continue
                    user = c.get("user", {})
                    comments.append({
                        "external_id":    str(c.get("pk", "")),
                        "author":         user.get("username", ""),
                        "author_id":      str(user.get("pk") or user.get("id", "")),
                        "author_name":    user.get("full_name", ""),
                        "author_verified": bool(user.get("is_verified", False)),
                        "raw_text":       text,
                        "likes":          int(c.get("comment_like_count", 0) or 0),
                        "reply_count":    int(c.get("child_comment_count", 0) or 0),
                        "liked_by_owner": bool(c.get("is_liked_by_media_owner", False)),
                        "posted_at":      _ts(c.get("created_at")),
                    })
                except (json.JSONDecodeError, AttributeError, TypeError) as e:
                    logger.debug("Instagram line %d skip: %s", i, e)
        return comments
