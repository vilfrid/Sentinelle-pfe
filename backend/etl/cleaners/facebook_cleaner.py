"""Extracts comment text from Facebook JSONL files."""
import json
import logging
from pathlib import Path
from typing import List, Dict

logger = logging.getLogger(__name__)


class FacebookCleaner:
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
                    node = data.get("node", {})
                    message = node.get("message", {}).get("text", "").replace("\n", " ").strip()
                    if message:
                        comments.append({
                            "external_id": node.get("id", ""),
                            "author": node.get("author", {}).get("name", ""),
                            "raw_text": message,
                            "likes": node.get("feedback", {}).get("reactors", {}).get("count", 0),
                        })
                except (json.JSONDecodeError, AttributeError, TypeError) as e:
                    logger.debug("Facebook line %d skip: %s", i, e)
        return comments
