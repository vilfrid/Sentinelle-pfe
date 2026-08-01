"""
Full ETL pipeline: JSONL → cleaned comments → stored in DB.
(Arabizi transformer removed — pipeline works directly with raw/cleaned text.)
"""
import logging
from pathlib import Path
from typing import List, Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.comment import Comment
from app.models.post import Post
from app.core.privacy import pseudonymize
from etl.cleaners import CLEANERS

logger = logging.getLogger(__name__)


class ETLPipeline:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def run(self, post_id: int, jsonl_path: Path, platform: str) -> int:
        """Run full pipeline for a scraped post. Returns number of comments stored."""
        cleaner_cls = CLEANERS.get(platform)
        if not cleaner_cls:
            raise ValueError(f"No cleaner for platform: {platform}")

        cleaner = cleaner_cls()
        raw_comments = cleaner.extract_comments(jsonl_path)
        logger.info("Extracted %d raw comments from %s", len(raw_comments), jsonl_path)

        if not raw_comments:
            return 0

        stored = 0
        for raw in raw_comments:
            existing = await self.db.scalar(
                select(Comment).where(
                    Comment.post_id == post_id,
                    Comment.external_id == raw.get("external_id", ""),
                )
            )
            if existing:
                continue

            comment = Comment(
                post_id=post_id,
                external_id=raw.get("external_id", ""),
                author=pseudonymize(raw.get("author", "")),   # RGPD: pseudonymise at ingestion
                raw_text=raw["raw_text"],
                cleaned_text=raw["raw_text"],
                language="raw",
                likes=raw.get("likes", 0),
            )
            self.db.add(comment)
            stored += 1

        result = await self.db.execute(
            select(Post).where(Post.id == post_id)
        )
        post = result.scalar_one_or_none()
        if post:
            post.etl_status = "transformed"

        await self.db.commit()
        logger.info("Stored %d new comments for post %d", stored, post_id)
        return stored
