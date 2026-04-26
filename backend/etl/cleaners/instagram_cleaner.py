"""Extracts comment text from Instagram JSONL files (PolarisPostCommentsPaginationQuery)."""
import json
import logging
from pathlib import Path
from typing import List, Dict

logger = logging.getLogger(__name__)

_XDT_PREFIX = "xdt_api__v1__media__"


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
                    data = record.get("data", record)
                    # navigate dynamic xdt key
                    xdt_key = next((k for k in data if k.startswith(_XDT_PREFIX)), None)
                    if not xdt_key:
                        continue
                    edges = data[xdt_key].get("edges", [])
                    for edge in edges:
                        node = edge.get("node", {}) if isinstance(edge, dict) else {}
                        text = node.get("text", "").replace("\n", " ").strip()
                        if text:
                            comments.append({
                                "external_id": node.get("id", ""),
                                "author": node.get("owner", {}).get("username", ""),
                                "raw_text": text,
                                "likes": node.get("edge_liked_by", {}).get("count", 0),
                            })
                except (json.JSONDecodeError, AttributeError, TypeError) as e:
                    logger.debug("Instagram line %d skip: %s", i, e)
        return comments
