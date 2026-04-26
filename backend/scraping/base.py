from abc import ABC, abstractmethod
from pathlib import Path
import json
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


class BaseScraper(ABC):
    platform: str = ""

    def __init__(self, output_dir: str = "data/raw"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def _get_output_path(self, post_id: str) -> Path:
        platform_dir = self.output_dir / self.platform
        platform_dir.mkdir(parents=True, exist_ok=True)
        return platform_dir / f"{post_id}.jsonl"

    def _append_record(self, path: Path, data: dict, friendly_name: str = ""):
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "platform": self.platform,
            "friendly_name": friendly_name,
            "data": data,
        }
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    @abstractmethod
    async def scrape(self, url: str, **kwargs) -> Path:
        """Scrape a post/video URL and return the output JSONL path."""
        ...
