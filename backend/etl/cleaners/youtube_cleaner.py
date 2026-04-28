"""Extracts comment text from YouTube JSONL files (yt-dlp format)."""
import json
import logging
from pathlib import Path
from typing import List, Dict

logger = logging.getLogger(__name__)


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
                    # _append_record wraps data under "data" key
                    data = record.get("data", record)
                    text = data.get("text", "").replace("\n", " ").strip()
                    if text:
                        comments.append({
                            "external_id": data.get("id", ""),
                            "author": data.get("author", ""),
                            "raw_text": text,
                            "likes": data.get("like_count", 0) or 0,
                        })
                except (json.JSONDecodeError, AttributeError, TypeError) as e:
                    logger.debug("YouTube line %d skip: %s", i, e)
        return comments
