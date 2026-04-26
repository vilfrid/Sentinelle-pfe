from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.database import get_db
from app.models.campaign import Campaign
from app.models.comment import Comment
from app.models.post import Post
from app.models.metric import Metric

router = APIRouter()


@router.get("/overview")
async def get_overview(db: AsyncSession = Depends(get_db)):
    total_campaigns = await db.scalar(select(func.count(Campaign.id)))
    total_posts = await db.scalar(select(func.count(Post.id)))
    total_comments = await db.scalar(select(func.count(Comment.id)))
    analyzed = await db.scalar(
        select(func.count(Comment.id)).where(Comment.sentiment.isnot(None))
    )
    positive = await db.scalar(
        select(func.count(Comment.id)).where(Comment.sentiment == "positive")
    )
    negative = await db.scalar(
        select(func.count(Comment.id)).where(Comment.sentiment == "negative")
    )
    neutral = await db.scalar(
        select(func.count(Comment.id)).where(Comment.sentiment == "neutral")
    )

    # latest negative spike alerts
    spikes = (await db.scalars(
        select(Metric)
        .where(Metric.negative_spike == 1)
        .order_by(Metric.computed_at.desc())
        .limit(5)
    )).all()

    return {
        "total_campaigns": total_campaigns or 0,
        "total_posts": total_posts or 0,
        "total_comments": total_comments or 0,
        "analyzed_comments": analyzed or 0,
        "sentiment_breakdown": {
            "positive": positive or 0,
            "negative": negative or 0,
            "neutral": neutral or 0,
        },
        "negative_spike_alerts": [
            {
                "campaign_id": s.campaign_id,
                "period": s.period,
                "negative_pct": round(s.negative_count / max(s.total_comments, 1) * 100, 1),
                "detected_at": s.computed_at.isoformat(),
            }
            for s in spikes
        ],
    }


@router.get("/sentiment-timeline/{campaign_id}")
async def sentiment_timeline(campaign_id: int, db: AsyncSession = Depends(get_db)):
    metrics = (await db.scalars(
        select(Metric)
        .where(Metric.campaign_id == campaign_id)
        .order_by(Metric.period_start)
    )).all()

    return [
        {
            "date": m.period_start.isoformat(),
            "positive": m.positive_count,
            "negative": m.negative_count,
            "neutral": m.neutral_count,
            "avg_score": m.avg_sentiment_score,
            "mood": m.audience_mood,
        }
        for m in metrics
    ]
