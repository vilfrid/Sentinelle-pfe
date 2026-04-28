"""Extracts comment text from Instagram JSONL files (private API format)."""
import json
import logging
from pathlib import Path
from typing import List, Dict

logger = logging.getLogger(__name__)


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
                    # _append_record wraps each comment under "data"
                    comment = record.get("data", record)
                    text = comment.get("text", "").replace("\n", " ").strip()
                    if text:
                        comments.append({
                            "external_id": str(comment.get("pk", "")),
                            "author": comment.get("user", {}).get("username", ""),
                            "raw_text": text,
                            "likes": comment.get("comment_like_count", 0),
                        })
                except (json.JSONDecodeError, AttributeError, TypeError) as e:
                    logger.debug("Instagram line %d skip: %s", i, e)
        return comments
