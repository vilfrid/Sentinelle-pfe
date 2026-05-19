"""Extracts comment and video metadata from YouTube JSONL files (yt-dlp format).

Real API shape per comment record (data field):
  id                  → external_id
  text                → raw_text
  timestamp           → posted_at (Unix timestamp)
  like_count          → likes
  author              → author (@handle)
  author_id           → author_id (UCxxxxxx)
  author_is_uploader  → is_creator_reply (quality/engagement signal)
  author_is_verified  → author_verified
  is_favorited        → hearted by creator (strong engagement signal)
  is_pinned           → pinned comment
  parent              → "root" or parent comment id (identifies replies)

Video metadata record shape (data.__type == "meta"):
  view_count          → post.views
  like_count          → post.likes
  comment_count       → post.comment_count
  description         → post.caption
  upload_date         → post.posted_at (format "YYYYMMDD")
  channel_follower_count → creator.follower_count
  channel             → creator.display_name
  uploader_id         → creator.username (@handle)
  thumbnail           → creator.avatar_url
  duration            → video length in seconds
  tags                → content tags
"""
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)


def _ts(unix: int | None) -> datetime | None:
    if not unix:
        return None
    try:
        return datetime.fromtimestamp(int(unix), tz=timezone.utc)
    except (TypeError, ValueError, OSError):
        return None


class YouTubeCleaner:
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
                    # Skip meta records
                    if data.get("__type") == "meta":
                        continue
                    text = data.get("text", "").replace("\n", " ").strip()
                    if not text:
                        continue
                    comments.append({
                        "external_id":      data.get("id", ""),
                        "author":           data.get("author", ""),
                        "author_id":        data.get("author_id", ""),
                        "author_verified":  bool(data.get("author_is_verified", False)),
                        "is_creator_reply": bool(data.get("author_is_uploader", False)),
                        "is_hearted":       bool(data.get("is_favorited", False)),
                        "is_pinned":        bool(data.get("is_pinned", False)),
                        "is_reply":         data.get("parent", "root") != "root",
                        "raw_text":         text,
                        "likes":            int(data.get("like_count", 0) or 0),
                        "posted_at":        _ts(data.get("timestamp")),
                    })
                except (json.JSONDecodeError, AttributeError, TypeError) as e:
                    logger.debug("YouTube line %d skip: %s", i, e)
        return comments

    def extract_post_metadata(self, jsonl_path: Path) -> Optional[Dict]:
        """Return the video-level metadata record saved by YouTubeScraper."""
        try:
            with open(jsonl_path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    record = json.loads(line)
                    data = record.get("data", record)
                    if data.get("__type") == "meta":
                        return data
        except Exception as e:
            logger.warning("YouTubeCleaner.extract_post_metadata failed: %s", e)
        return None
