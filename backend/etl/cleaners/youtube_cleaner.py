"""Extracts comment text from YouTube JSONL files (/youtubei/v1/next)."""
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
                    data = record.get("data", record)
                    mutations = (
                        data.get("frameworkUpdates", {})
                        .get("entityBatchUpdate", {})
                        .get("mutations", [])
                    )
                    for mut in mutations:
                        payload = mut.get("payload", {}).get("commentEntityPayload")
                        if not payload:
                            continue
                        content = (
                            payload.get("properties", {})
                            .get("content", {})
                            .get("content", "")
                        )
                        if content:
                            comments.append({
                                "external_id": payload.get("properties", {}).get("commentId", ""),
                                "author": payload.get("author", {}).get("displayName", ""),
                                "raw_text": content.replace("\n", " ").strip(),
                                "likes": payload.get("toolbar", {}).get("likeCountLiked", 0),
                            })
                except (json.JSONDecodeError, AttributeError, TypeError) as e:
                    logger.debug("YouTube line %d skip: %s", i, e)
        return comments
