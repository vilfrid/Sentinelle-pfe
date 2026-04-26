"""Extracts comment text from TikTok JSONL files (from scraping.tiktok)."""
import json
import logging
from pathlib import Path
from typing import List, Dict

logger = logging.getLogger(__name__)


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
                        if text:
                            comments.append({
                                "external_id": str(c.get("cid", "")),
                                "author": c.get("user", {}).get("unique_id", ""),
                                "raw_text": text,
                                "likes": c.get("digg_count", 0),
                            })
                except (json.JSONDecodeError, AttributeError) as e:
                    logger.debug("TikTok line %d skip: %s", i, e)
        return comments
