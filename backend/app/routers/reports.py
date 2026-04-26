from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List

from app.database import get_db
from app.models.report import Report
from app.models.metric import Metric
from app.schemas.report import ReportCreate, ReportOut

router = APIRouter()


@router.get("/", response_model=List[ReportOut])
async def list_reports(db: AsyncSession = Depends(get_db)):
    result = await db.scalars(select(Report).order_by(Report.created_at.desc()))
    return result.all()


@router.post("/generate", response_model=ReportOut, status_code=201)
async def generate_report(payload: ReportCreate, db: AsyncSession = Depends(get_db)):
    latest_metric = await db.scalar(
        select(Metric)
        .where(Metric.campaign_id == payload.campaign_id)
        .order_by(Metric.computed_at.desc())
    )

    what_worked = []
    what_to_improve = []
    recommendations = []
    summary = ""
    metrics_snapshot = {}

    if latest_metric:
        metrics_snapshot = {
            "total_comments": latest_metric.total_comments,
            "positive_pct": round(latest_metric.positive_count / max(latest_metric.total_comments, 1) * 100, 1),
            "negative_pct": round(latest_metric.negative_count / max(latest_metric.total_comments, 1) * 100, 1),
            "engagement_rate": latest_metric.engagement_rate,
            "virality_score": latest_metric.virality_score,
            "audience_mood": latest_metric.audience_mood,
        }
        pos_pct = metrics_snapshot["positive_pct"]
        neg_pct = metrics_snapshot["negative_pct"]

        summary = (
            f"Campaign analyzed {latest_metric.total_comments} comments. "
            f"Audience mood: {latest_metric.audience_mood}. "
            f"Positive: {pos_pct}%, Negative: {neg_pct}%."
        )

        if pos_pct > 60:
            what_worked.append("Strong positive audience reception")
        if latest_metric.engagement_rate > 0.05:
            what_worked.append("Above-average engagement rate")
        if latest_metric.virality_score > 0.1:
            what_worked.append("Content showing viral potential")

        if neg_pct > 30:
            what_to_improve.append("Address recurring negative feedback themes")
        if latest_metric.negative_spike:
            what_to_improve.append("Investigate and respond to the negative spike detected")
        if latest_metric.engagement_rate < 0.02:
            what_to_improve.append("Improve content hook to boost engagement")

        recommendations.append("Post during peak engagement hours for the Tunisian audience")
        if latest_metric.trending_topics:
            top = latest_metric.trending_topics[0]["topic"] if latest_metric.trending_topics else ""
            if top:
                recommendations.append(f"Leverage trending topic '{top}' in upcoming content")

    report = Report(
        campaign_id=payload.campaign_id,
        title=payload.title,
        period_start=payload.period_start,
        period_end=payload.period_end,
        summary=summary,
        what_worked=what_worked,
        what_to_improve=what_to_improve,
        recommendations=recommendations,
        metrics_snapshot=metrics_snapshot,
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
