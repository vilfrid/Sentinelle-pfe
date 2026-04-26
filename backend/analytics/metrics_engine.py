"""
Metrics engine: computes impression score, virality, engagement rate,
audience mood, and negative spike detection for a campaign period.
"""
import logging
from datetime import datetime, timezone
from typing import List

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_

from app.models.comment import Comment
from app.models.post import Post
from app.models.metric import Metric
from app.models.campaign import Campaign

logger = logging.getLogger(__name__)

_NEGATIVE_SPIKE_THRESHOLD = 0.4  # >40% negative → spike alert


class MetricsEngine:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def compute(self, campaign_id: int, period: str, start: datetime, end: datetime) -> Metric:
        posts = (await self.db.scalars(
            select(Post).where(
                Post.campaign_id == campaign_id,
                Post.scraped_at.between(start, end),
            )
        )).all()

        post_ids = [p.id for p in posts]
        comments: List[Comment] = []
        if post_ids:
            comments = (await self.db.scalars(
                select(Comment).where(Comment.post_id.in_(post_ids))
            )).all()

        total = len(comments)
        positive = sum(1 for c in comments if c.sentiment == "positive")
        negative = sum(1 for c in comments if c.sentiment == "negative")
        neutral = total - positive - negative

        avg_score = (
            sum(c.sentiment_score for c in comments if c.sentiment_score is not None) / total
            if total > 0 else 0.0
        )

        total_likes = sum(p.likes for p in posts)
        total_views = sum(p.views for p in posts) or 1
        total_shares = sum(p.shares for p in posts)
        total_interactions = total_likes + len(comments) + total_shares
        engagement_rate = total_interactions / total_views

        # Impression score: weighted estimate (views × engagement multiplier)
        impression_score = total_views * (1 + engagement_rate * 5)

        # Virality: shares relative to total interactions
        virality_score = total_shares / max(total_interactions, 1)

        # Mood
        if total == 0:
            mood = "neutral"
            mood_shift = 0.0
        elif positive / total > 0.6:
            mood = "happy"
            mood_shift = avg_score
        elif negative / total > _NEGATIVE_SPIKE_THRESHOLD:
            mood = "angry"
            mood_shift = avg_score
        elif abs(avg_score) < 0.15:
            mood = "neutral"
            mood_shift = 0.0
        else:
            mood = "mixed"
            mood_shift = avg_score

        negative_spike = 1 if total > 0 and negative / total > _NEGATIVE_SPIKE_THRESHOLD else 0

        metric = Metric(
            campaign_id=campaign_id,
            period=period,
            period_start=start,
            period_end=end,
            total_comments=total,
            total_posts=len(posts),
            positive_count=positive,
            negative_count=negative,
            neutral_count=neutral,
            avg_sentiment_score=round(avg_score, 4),
            impression_score=round(impression_score, 2),
            virality_score=round(virality_score, 4),
            engagement_rate=round(engagement_rate, 4),
            audience_mood=mood,
            mood_shift=round(mood_shift, 4),
            negative_spike=negative_spike,
        )
        self.db.add(metric)
        await self.db.commit()
        await self.db.refresh(metric)
        return metric
