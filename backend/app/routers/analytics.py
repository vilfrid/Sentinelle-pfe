from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List
from datetime import datetime, timezone, timedelta

from app.database import get_db
from app.models.metric import Metric
from app.schemas.metric import MetricOut
from analytics.metrics_engine import MetricsEngine

router = APIRouter()


@router.get("/{campaign_id}/metrics", response_model=List[MetricOut])
async def list_metrics(campaign_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.scalars(
        select(Metric)
        .where(Metric.campaign_id == campaign_id)
        .order_by(Metric.period_start.desc())
    )
    return result.all()


@router.post("/{campaign_id}/compute", response_model=MetricOut)
async def compute_metrics(
    campaign_id: int,
    period: str = Query("weekly", enum=["daily", "weekly", "monthly"]),
    db: AsyncSession = Depends(get_db),
):
    now = datetime.now(timezone.utc)
    delta = {"daily": timedelta(days=1), "weekly": timedelta(weeks=1), "monthly": timedelta(days=30)}
    start = now - delta[period]
    engine = MetricsEngine(db)
    return await engine.compute(campaign_id, period, start, now)


@router.get("/{campaign_id}/topics")
async def get_topics(campaign_id: int, db: AsyncSession = Depends(get_db)):
    from app.models.comment import Comment
    from app.models.post import Post
    from app.models.creator import Creator
    from analytics.topics_engine import extract_hashtags

    # Use topics already computed by finalize_creator (no live AI call needed)
    creators = (await db.scalars(
        select(Creator).where(Creator.campaign_id == campaign_id)
    )).all()

    topic_counts: dict = {}
    for creator in creators:
        if not creator.top_topics:
            continue
        for t in creator.top_topics:
            topic = t.get("topic") if isinstance(t, dict) else str(t)
            count = int(t.get("count", 1)) if isinstance(t, dict) else 1
            if topic:
                topic_counts[topic] = topic_counts.get(topic, 0) + count

    topics = [
        {"topic": topic, "count": count}
        for topic, count in sorted(topic_counts.items(), key=lambda x: -x[1])
    ][:20]

    # Hashtags from raw comment text (fast regex, no AI)
    posts = (await db.scalars(select(Post).where(Post.campaign_id == campaign_id))).all()
    post_ids = [p.id for p in posts]
    texts: list = []
    if post_ids:
        comments = (await db.scalars(
            select(Comment).where(Comment.post_id.in_(post_ids))
        )).all()
        texts = [c.raw_text for c in comments if c.raw_text]

    return {"topics": topics, "hashtags": extract_hashtags(texts)}
