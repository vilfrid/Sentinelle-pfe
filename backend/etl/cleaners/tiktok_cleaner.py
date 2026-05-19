"""Extracts comment data from TikTok JSONL files (Playwright-intercepted API).

Real API shape — each JSONL line wraps the full batch response under "data":
  data.comments[].cid                → external_id
  data.comments[].text               → raw_text
  data.comments[].create_time        → posted_at (Unix timestamp)
  data.comments[].digg_count         → likes
  data.comments[].reply_comment_total → reply_count
  data.comments[].reply_id           → "0" = top-level, else parent cid
  data.comments[].user.unique_id     → author (@handle)
  data.comments[].user.uid           → author_id
  data.comments[].user.nickname      → author_display_name
  data.comments[].user.verified      → author_verified
  data.total                         → total comment count on the video
  data.has_more / data.cursor        → pagination state (not stored, for scraper use)
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


class TikTokCleaner:
    def extract_comments(self, jsonl_path: Path) -> List[Dict]:
        comments = []
        with open(jsonl_path, encoding="utf-8") as f:
            for i, line in enumerate(f):
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                    data = record.get("data", record)
                    for c in data.get("comments", []):
                        text = c.get("text", "").replace("\n", " ").strip()
                        if not text:
                            continue
                        user = c.get("user", {})
                        reply_id = str(c.get("reply_id", "0"))
                        comments.append({
                            "external_id":    str(c.get("cid", "")),
                            "author":         user.get("unique_id", ""),
                            "author_id":      str(user.get("uid", "")),
                            "author_name":    user.get("nickname", ""),
                            "author_verified": bool(user.get("verified", False)),
                            "raw_text":       text,
                            "likes":          int(c.get("digg_count", 0) or 0),
                            "reply_count":    int(c.get("reply_comment_total", 0) or 0),
                            "is_reply":       reply_id != "0",
                            "parent_id":      reply_id if reply_id != "0" else None,
                            "posted_at":      _ts(c.get("create_time")),
                        })
                except (json.JSONDecodeError, AttributeError) as e:
                    logger.debug("TikTok line %d skip: %s", i, e)
        return comments
