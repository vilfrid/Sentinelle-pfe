from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from typing import List

from app.database import get_db
from app.models.report import Report
from app.models.metric import Metric
from app.models.campaign import Campaign
from app.models.creator import Creator
from app.models.post import Post
from app.models.comment import Comment
from app.schemas.report import ReportCreate, ReportOut
from analytics.report_generator import ReportGenerator

router = APIRouter()


@router.get("/", response_model=List[ReportOut])
async def list_reports(db: AsyncSession = Depends(get_db)):
    result = await db.scalars(select(Report).order_by(Report.created_at.desc()))
    return result.all()


@router.post("/generate", response_model=ReportOut, status_code=201)
async def generate_report(payload: ReportCreate, db: AsyncSession = Depends(get_db)):
    """Generate an AI-powered campaign performance report using Google Gemini."""

    campaign = await db.get(Campaign, payload.campaign_id)
    if not campaign:
        raise HTTPException(404, "Campaign not found")

    # ── Gather metrics ──
    latest_metric = await db.scalar(
        select(Metric)
        .where(Metric.campaign_id == payload.campaign_id)
        .order_by(Metric.computed_at.desc())
    )

    # Aggregate from comments if no precomputed metric exists
    posts = (await db.scalars(
        select(Post).where(Post.campaign_id == payload.campaign_id)
    )).all()
    post_ids = [p.id for p in posts]

    total_comments = 0
    positive_count = 0
    negative_count = 0
    comments_list = []

    if post_ids:
        comments_list = (await db.scalars(
            select(Comment).where(Comment.post_id.in_(post_ids))
        )).all()
        total_comments = len(comments_list)
        positive_count = sum(1 for c in comments_list if c.sentiment == "positive")
        negative_count = sum(1 for c in comments_list if c.sentiment == "negative")

    neutral_count = total_comments - positive_count - negative_count

    metrics_data = {
        "total_comments": total_comments,
        "total_posts": len(posts),
        "positive_pct": round(positive_count / max(total_comments, 1) * 100, 1),
        "negative_pct": round(negative_count / max(total_comments, 1) * 100, 1),
        "neutral_pct": round(neutral_count / max(total_comments, 1) * 100, 1),
        "engagement_rate": latest_metric.engagement_rate if latest_metric else 0,
        "virality_score": latest_metric.virality_score if latest_metric else 0,
        "audience_mood": latest_metric.audience_mood if latest_metric else "unknown",
    }

    # ── Trending topics via AI ──
    from analytics.topics_engine import extract_topics_with_ai
    texts = [c.cleaned_text or c.raw_text for c in comments_list if c.cleaned_text or c.raw_text]
    trending_topics = extract_topics_with_ai(texts, top_n=15) if texts else []

    # ── Sample comments: best positive + worst negative ──
    positive_comments = sorted(
        [c for c in comments_list if c.sentiment == "positive" and c.sentiment_score is not None],
        key=lambda c: c.sentiment_score or 0,
        reverse=True,
    )[:10]
    negative_comments = sorted(
        [c for c in comments_list if c.sentiment == "negative" and c.sentiment_score is not None],
        key=lambda c: c.sentiment_score or 0,
    )[:10]
    sample_comments = [
        {"text": c.cleaned_text or c.raw_text or "", "sentiment": c.sentiment, "score": c.sentiment_score}
        for c in positive_comments + negative_comments
    ]

    # ── Creator summaries (ranked by comment volume) ──
    creators = (await db.scalars(
        select(Creator).where(Creator.campaign_id == payload.campaign_id)
    )).all()
    creator_summaries = sorted(
        [
            {
                "username": cr.username,
                "total_comments": cr.total_comments or 0,
                "mood": cr.audience_mood or "unknown",
                "positive_pct": cr.positive_pct or 0,
                "negative_pct": cr.negative_pct or 0,
            }
            for cr in creators
        ],
        key=lambda c: c["total_comments"],
        reverse=True,
    )

    # ── Generate AI report ──
    generator = ReportGenerator()
    ai_result = generator.generate(
        campaign_name=campaign.name,
        brand=campaign.brand,
        metrics=metrics_data,
        trending_topics=trending_topics,
        sample_comments=sample_comments,
        creator_summaries=creator_summaries,
    )

    # Store new AI sections + creator/topic data in metrics_snapshot (no schema change needed)
    full_snapshot = {
        **metrics_data,
        "trending_topics": trending_topics,
        "creator_summaries": creator_summaries,
        "sentiment_insights": ai_result.get("sentiment_insights", ""),
        "risk_alerts": ai_result.get("risk_alerts", []),
        "audience_insights": ai_result.get("audience_insights", []),
    }

    report = Report(
        campaign_id=payload.campaign_id,
        title=payload.title,
        period_start=payload.period_start,
        period_end=payload.period_end,
        summary=ai_result["summary"],
        what_worked=ai_result["what_worked"],
        what_to_improve=ai_result["what_to_improve"],
        recommendations=ai_result["recommendations"],
        metrics_snapshot=full_snapshot,
        status="published",
    )
    db.add(report)
    await db.commit()
    await db.refresh(report)
    return report


@router.get("/{report_id}", response_model=ReportOut)
async def get_report(report_id: int, db: AsyncSession = Depends(get_db)):
    report = await db.get(Report, report_id)
    if not report:
        raise HTTPException(404, "Report not found")
    return report
