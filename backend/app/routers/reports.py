import re
from collections import Counter
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

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

_HASHTAG_RE = re.compile(r"#(\w+)")


def _extract_hashtags(caption: str) -> List[str]:
    if not caption:
        return []
    return [t.lower() for t in _HASHTAG_RE.findall(caption)]


def _fmt_num(n) -> str:
    n = int(n or 0)
    if n >= 1_000_000:
        return f"{n/1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n/1_000:.1f}K"
    return str(n)


def _compute_hashtag_trends(posts: list) -> dict:
    """
    Split posts into older (first 60%) and recent (last 40%) by posted_at.
    Compare hashtag frequency to classify tags as: trending_now / fading / stable.
    Returns { trending_now, fading, stable, top_all_time }.
    """
    dated = sorted([p for p in posts if p.posted_at], key=lambda p: p.posted_at)
    undated = [p for p in posts if not p.posted_at]

    if len(dated) >= 4:
        cutoff = max(1, int(len(dated) * 0.60))
        older_posts  = dated[:cutoff]
        recent_posts = dated[cutoff:]
    else:
        # not enough dated posts — treat all as current
        older_posts  = []
        recent_posts = dated + undated

    all_counter    = Counter()
    older_counter  = Counter()
    recent_counter = Counter()

    for p in older_posts:
        tags = _extract_hashtags(p.caption or "")
        older_counter.update(tags)
        all_counter.update(tags)

    for p in recent_posts:
        tags = _extract_hashtags(p.caption or "")
        recent_counter.update(tags)
        all_counter.update(tags)

    n_older  = max(len(older_posts), 1)
    n_recent = max(len(recent_posts), 1)

    trending_now = []
    fading       = []
    stable       = []

    all_tags = set(all_counter.keys())
    for tag in all_tags:
        r_count = recent_counter.get(tag, 0)
        o_count = older_counter.get(tag, 0)
        r_rate  = r_count / n_recent
        o_rate  = o_count / n_older

        entry = {"tag": f"#{tag}", "recent_uses": r_count, "old_uses": o_count}

        if r_rate >= o_rate * 1.5 and r_count >= 2:
            trending_now.append(entry)
        elif o_rate >= r_rate * 1.5 and o_count >= 2:
            fading.append(entry)
        elif r_count >= 1 and o_count >= 1:
            stable.append(entry)

    trending_now.sort(key=lambda x: x["recent_uses"], reverse=True)
    fading.sort(key=lambda x: x["old_uses"], reverse=True)
    stable.sort(key=lambda x: x["recent_uses"] + x["old_uses"], reverse=True)

    top_all_time = [f"#{tag}" for tag, _ in all_counter.most_common(15)]

    return {
        "trending_now": trending_now[:10],
        "fading":       fading[:10],
        "stable":       stable[:8],
        "top_all_time": top_all_time,
    }


def _compute_post_analytics(posts: list) -> dict:
    """Aggregate views/likes/shares and identify top performing posts."""
    if not posts:
        return {
            "total_views": 0, "total_likes": 0, "total_shares": 0,
            "avg_views_per_post": 0, "avg_likes_per_post": 0,
            "top_posts_by_views": [], "top_posts_by_likes": [],
        }

    post_rows = []
    for p in posts:
        hashtags = _extract_hashtags(p.caption or "")
        post_rows.append({
            "url":             p.url or "",
            "caption_preview": (p.caption or "")[:100],
            "likes":           p.likes or 0,
            "views":           p.views or 0,
            "shares":          p.shares or 0,
            "comment_count":   p.comment_count or 0,
            "hashtags":        hashtags,
            "posted_at":       p.posted_at.isoformat() if p.posted_at else None,
        })

    n = len(post_rows)
    total_views  = sum(p["views"] for p in post_rows)
    total_likes  = sum(p["likes"] for p in post_rows)
    total_shares = sum(p["shares"] for p in post_rows)

    return {
        "total_views":        total_views,
        "total_likes":        total_likes,
        "total_shares":       total_shares,
        "avg_views_per_post": round(total_views / n),
        "avg_likes_per_post": round(total_likes / n),
        "top_posts_by_views": sorted(post_rows, key=lambda p: p["views"], reverse=True)[:5],
        "top_posts_by_likes": sorted(post_rows, key=lambda p: p["likes"], reverse=True)[:5],
    }


@router.get("/", response_model=List[ReportOut])
async def list_reports(db: AsyncSession = Depends(get_db)):
    result = await db.scalars(select(Report).order_by(Report.created_at.desc()))
    return result.all()


@router.post("/generate", response_model=ReportOut, status_code=201)
async def generate_report(payload: ReportCreate, db: AsyncSession = Depends(get_db)):
    """Generate an AI-powered campaign performance report using Groq (Llama 3.3 70B)."""

    campaign = await db.get(Campaign, payload.campaign_id)
    if not campaign:
        raise HTTPException(404, "Campaign not found")

    # ── Gather posts & comments ──
    latest_metric = await db.scalar(
        select(Metric)
        .where(Metric.campaign_id == payload.campaign_id)
        .order_by(Metric.computed_at.desc())
    )

    posts = (await db.scalars(
        select(Post).where(Post.campaign_id == payload.campaign_id)
    )).all()
    post_ids = [p.id for p in posts]

    comments_list = []
    if post_ids:
        comments_list = (await db.scalars(
            select(Comment).where(Comment.post_id.in_(post_ids))
        )).all()

    total_comments = len(comments_list)
    positive_count = sum(1 for c in comments_list if c.sentiment == "positive")
    negative_count = sum(1 for c in comments_list if c.sentiment == "negative")
    neutral_count  = sum(1 for c in comments_list if c.sentiment == "neutral")
    analyzed_count = positive_count + negative_count + neutral_count

    # ── Post-level analytics (views, likes, hashtags) ──
    post_analytics   = _compute_post_analytics(posts)
    hashtag_trends   = _compute_hashtag_trends(posts)

    metrics_data = {
        "total_comments":    total_comments,
        "total_posts":       len(posts),
        "positive_pct":      round(positive_count / max(analyzed_count, 1) * 100, 1),
        "negative_pct":      round(negative_count / max(analyzed_count, 1) * 100, 1),
        "neutral_pct":       round(neutral_count  / max(analyzed_count, 1) * 100, 1),
        "engagement_rate":   latest_metric.engagement_rate if latest_metric else 0,
        "virality_score":    latest_metric.virality_score  if latest_metric else 0,
        "audience_mood":     latest_metric.audience_mood   if latest_metric else "unknown",
        "impression_score":  latest_metric.impression_score if latest_metric else 0,
        # Post engagement signals
        "total_views":           post_analytics["total_views"],
        "total_likes":           post_analytics["total_likes"],
        "total_shares":          post_analytics["total_shares"],
        "avg_views_per_post":    post_analytics["avg_views_per_post"],
        "avg_likes_per_post":    post_analytics["avg_likes_per_post"],
        "top_hashtags":          hashtag_trends["top_all_time"],
    }

    # ── Trending comment topics via AI (blocking → executor) ──
    import asyncio
    import random
    from analytics.topics_engine import extract_topics_with_ai
    all_texts = [c.cleaned_text or c.raw_text for c in comments_list if c.cleaned_text or c.raw_text]
    # Sample at most 300 comments — more causes 60+ batches and Qwen output truncation
    texts = random.sample(all_texts, min(300, len(all_texts))) if all_texts else []
    loop = asyncio.get_running_loop()
    trending_topics = await loop.run_in_executor(
        None, lambda: extract_topics_with_ai(texts, top_n=15) if texts else []
    )

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

    # ── Creator summaries ──
    creators = (await db.scalars(
        select(Creator).where(Creator.campaign_id == payload.campaign_id)
    )).all()

    # Load posts per creator to get their avg views/hashtags
    creator_post_map: dict = {}
    if post_ids:
        for p in posts:
            if p.creator_id not in creator_post_map:
                creator_post_map[p.creator_id] = []
            creator_post_map[p.creator_id].append(p)

    creator_summaries = sorted(
        [
            {
                "username":       cr.username,
                "total_comments": cr.total_comments or 0,
                "mood":           cr.audience_mood or "unknown",
                "positive_pct":   cr.positive_pct or 0,
                "negative_pct":   cr.negative_pct or 0,
                "follower_count": cr.follower_count or 0,
                "avg_views":      _avg_views(creator_post_map.get(cr.id, [])),
                "engagement_rate": _avg_engagement(creator_post_map.get(cr.id, [])),
                "top_hashtags":   _top_hashtags(creator_post_map.get(cr.id, []), top=5),
            }
            for cr in creators
        ],
        key=lambda c: c["total_comments"],
        reverse=True,
    )

    # ── Generate AI report (Groq is sync → executor) ──
    generator = ReportGenerator()
    try:
        ai_result = await loop.run_in_executor(
            None,
            lambda: generator.generate(
                campaign_name=campaign.name,
                brand=campaign.brand,
                metrics=metrics_data,
                trending_topics=trending_topics,
                sample_comments=sample_comments,
                creator_summaries=creator_summaries,
                post_analytics=post_analytics,
                hashtag_trends=hashtag_trends,
            ),
        )
    except RuntimeError as exc:
        raise HTTPException(500, f"Report generation failed: {exc}")

    full_snapshot = {
        **metrics_data,
        "trending_topics":    trending_topics,
        "creator_summaries":  creator_summaries,
        "post_analytics":     post_analytics,
        "hashtag_trends":     hashtag_trends,
        "sentiment_insights": ai_result.get("sentiment_insights", ""),
        "risk_alerts":        ai_result.get("risk_alerts", []),
        "audience_insights":  ai_result.get("audience_insights", []),
        "trending_now":       ai_result.get("trending_now", []),
        "fading_content":     ai_result.get("fading_content", []),
        "content_strategy":   ai_result.get("content_strategy", []),
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
        risk_alerts=ai_result.get("risk_alerts", []),
        audience_insights=ai_result.get("audience_insights", []),
        trending_now=ai_result.get("trending_now", []),
        fading_content=ai_result.get("fading_content", []),
        content_strategy=ai_result.get("content_strategy", []),
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


# ── Helpers ──────────────────────────────────────────────────────────────────

def _avg_views(posts: list) -> int:
    if not posts:
        return 0
    return round(sum(p.views or 0 for p in posts) / len(posts))


def _avg_engagement(posts: list) -> float:
    if not posts:
        return 0.0
    total_views = sum(p.views or 0 for p in posts)
    total_inter = sum((p.likes or 0) + (p.comment_count or 0) for p in posts)
    if total_views == 0:
        return 0.0
    return round(total_inter / total_views * 100, 2)


def _top_hashtags(posts: list, top: int = 5) -> List[str]:
    counter: Counter = Counter()
    for p in posts:
        counter.update(_extract_hashtags(p.caption or ""))
    return [tag for tag, _ in counter.most_common(top)]
