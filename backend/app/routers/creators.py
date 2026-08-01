from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete, func
from typing import List
from urllib.parse import urlparse
from pathlib import Path

from app.database import get_db
from app.models.creator import Creator
from app.models.platform import Platform
from app.models.post import Post
from app.models.comment import Comment
from app.schemas.creator import CreatorCreate, CreatorOut, CreatorUpdate

router = APIRouter()


def _extract_username(raw: str, platform: str) -> str:
    """Extract plain username from a URL or @handle."""
    raw = raw.strip().lstrip("@")
    if raw.startswith("http"):
        path = urlparse(raw).path.rstrip("/")
        # last non-empty path segment, strip leading @
        username = path.split("/")[-1].lstrip("@")
        return username or raw
    return raw


@router.get("/", response_model=List[CreatorOut])
async def list_creators(db: AsyncSession = Depends(get_db)):
    result = await db.scalars(select(Creator).order_by(Creator.created_at.desc()))
    return result.all()


@router.post("/", response_model=CreatorOut, status_code=201)
async def add_creator(payload: CreatorCreate, db: AsyncSession = Depends(get_db)):
    # Resolve or create platform
    platform = await db.scalar(select(Platform).where(Platform.name == payload.platform))
    if not platform:
        platform = Platform(name=payload.platform, display_name=payload.platform.capitalize())
        db.add(platform)
        await db.flush()

    username = _extract_username(payload.username, payload.platform)
    creator = Creator(
        platform_id=platform.id,
        campaign_id=payload.campaign_id,
        username=username,
        profile_url=payload.profile_url or _default_url(payload.platform, username),
        status="idle",
    )
    db.add(creator)
    await db.commit()
    await db.refresh(creator)

    # Kick off the pipeline immediately
    from workers.tasks import launch_creator_pipeline
    task = launch_creator_pipeline.delay(creator.id)
    creator.pipeline_task_id = task.id
    creator.status = "discovering"
    await db.commit()
    await db.refresh(creator)

    return creator


@router.get("/{creator_id}")
async def get_creator(creator_id: int, db: AsyncSession = Depends(get_db)):
    creator = await db.get(Creator, creator_id)
    if not creator:
        raise HTTPException(404, "Creator not found")
    posts = (await db.scalars(select(Post).where(Post.creator_id == creator_id))).all()
    n = len(posts)

    # Content-type breakdown
    reel_count     = sum(1 for p in posts if (p.media_type or 1) == 2)
    photo_count    = sum(1 for p in posts if (p.media_type or 1) == 1)
    carousel_count = sum(1 for p in posts if (p.media_type or 1) == 8)
    collab_count   = sum(1 for p in posts if p.is_collab)

    # Avg views: only over Reels/videos that actually reported play_count
    video_posts = [p for p in posts if (p.media_type or 1) == 2 and (p.views or 0) > 0]
    avg_views  = int(sum(p.views for p in video_posts) / len(video_posts)) if video_posts else 0
    avg_likes  = int(sum(p.likes or 0  for p in posts) / n) if n else 0
    avg_shares = int(sum(p.shares or 0 for p in posts) / n) if n else 0

    platform_obj = await db.get(Platform, creator.platform_id)
    platform_name = platform_obj.name if platform_obj else "instagram"

    data = CreatorOut.model_validate(creator).model_dump()
    data["avg_views"]      = avg_views
    data["avg_likes"]      = avg_likes
    data["avg_shares"]     = avg_shares
    data["reel_count"]     = reel_count
    data["photo_count"]    = photo_count
    data["carousel_count"] = carousel_count
    data["collab_count"]   = collab_count
    data["platform"]       = platform_name
    return data


@router.patch("/{creator_id}", response_model=CreatorOut)
async def update_creator(creator_id: int, payload: CreatorUpdate, db: AsyncSession = Depends(get_db)):
    creator = await db.get(Creator, creator_id)
    if not creator:
        raise HTTPException(404, "Creator not found")
    
    # If linking to a new campaign, update all existing posts as well
    if payload.campaign_id is not None and creator.campaign_id != payload.campaign_id:
        from sqlalchemy import update
        from app.models.post import Post
        await db.execute(
            update(Post)
            .where(Post.creator_id == creator_id)
            .values(campaign_id=payload.campaign_id)
        )
    
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(creator, field, value)
        
    await db.commit()
    await db.refresh(creator)
    return creator


@router.post("/{creator_id}/refresh", response_model=CreatorOut)
async def refresh_creator(creator_id: int, db: AsyncSession = Depends(get_db)):
    """Re-trigger the full pipeline for an existing creator."""
    creator = await db.get(Creator, creator_id)
    if not creator:
        raise HTTPException(404, "Creator not found")

    from workers.tasks import launch_creator_pipeline
    task = launch_creator_pipeline.delay(creator.id)
    creator.pipeline_task_id = task.id
    creator.status = "discovering"
    creator.error_message = None
    await db.commit()
    await db.refresh(creator)
    return creator


@router.post("/{creator_id}/restart", response_model=CreatorOut)
async def restart_creator_pipeline(creator_id: int, db: AsyncSession = Depends(get_db)):
    """Wipe all comments and posts for this creator, then re-run the full pipeline from scratch."""
    creator = await db.get(Creator, creator_id)
    if not creator:
        raise HTTPException(404, "Creator not found")

    from workers.tasks import launch_creator_pipeline, set_stop_flag, clear_logs

    set_stop_flag(creator_id)

    posts = (await db.scalars(select(Post).where(Post.creator_id == creator_id))).all()
    post_ids = [p.id for p in posts]
    if post_ids:
        await db.execute(delete(Comment).where(Comment.post_id.in_(post_ids)))
        await db.execute(
            Post.__table__.update()
            .where(Post.creator_id == creator_id)
            .values(etl_status="pending", raw_data_path=None)
        )

    creator.total_comments = 0
    creator.total_posts_scraped = 0
    creator.positive_pct = 0
    creator.negative_pct = 0
    creator.neutral_pct = 0
    creator.avg_sentiment_score = 0
    creator.audience_mood = None
    creator.top_topics = None
    creator.error_message = None
    await db.commit()

    clear_logs(creator_id)
    task = launch_creator_pipeline.delay(creator_id)
    creator.pipeline_task_id = task.id
    creator.status = "discovering"
    await db.commit()
    await db.refresh(creator)
    return creator


@router.post("/{creator_id}/recompute-topics")
async def recompute_topics(creator_id: int, db: AsyncSession = Depends(get_db)):
    """Re-run AI topic extraction on existing comments without re-scraping."""
    import asyncio
    import json
    from functools import partial

    creator = await db.get(Creator, creator_id)
    if not creator:
        raise HTTPException(404, "Creator not found")

    # Gather all comments for this creator's posts
    post_ids = (await db.scalars(
        select(Post.id).where(Post.creator_id == creator_id)
    )).all()

    if not post_ids:
        raise HTTPException(400, "No posts found for this creator")

    comments = (await db.scalars(
        select(Comment).where(Comment.post_id.in_(post_ids))
    )).all()

    texts = [c.cleaned_text or c.raw_text for c in comments if c.cleaned_text or c.raw_text]
    if not texts:
        raise HTTPException(400, "No comment texts available to extract topics from")

    # Run AI topic extraction in a thread to avoid blocking the async loop
    from analytics.topics_engine import extract_topics_with_ai
    loop = asyncio.get_running_loop()
    top_topics = await loop.run_in_executor(None, partial(extract_topics_with_ai, texts, 10))

    creator.top_topics = top_topics

    # Regenerate content embedding so matching stays accurate
    try:
        from analytics.embedding_service import EmbeddingService
        svc = EmbeddingService()
        topic_names = [t["topic"] for t in top_topics] if top_topics else []
        summary = svc.build_creator_text(creator.username, creator.bio, topic_names, creator.audience_mood)
        embedding = svc.generate_embedding(summary)
        if embedding:
            creator.content_summary = summary
            creator.content_embedding = json.dumps(embedding)
    except Exception:
        pass  # non-fatal

    await db.commit()
    await db.refresh(creator)
    return {"topics": top_topics}


@router.post("/{creator_id}/finalize", status_code=202)
async def finalize_creator_now(creator_id: int, db: AsyncSession = Depends(get_db)):
    """Stop ongoing scraping and aggregate whatever has been collected so far."""
    creator = await db.get(Creator, creator_id)
    if not creator:
        raise HTTPException(404, "Creator not found")

    from workers.tasks import set_stop_flag, finalize_creator, _log
    set_stop_flag(creator_id)
    _log(creator_id, "finalize", "info", "Early finalize requested — stopping scrape and aggregating results")

    creator.status = "processing"
    creator.error_message = None
    await db.commit()

    finalize_creator.delay([], creator_id)
    return {"status": "finalizing"}


@router.post("/{creator_id}/stop", status_code=204)
async def stop_creator_pipeline(creator_id: int, db: AsyncSession = Depends(get_db)):
    """Signal running pipeline tasks to abort."""
    creator = await db.get(Creator, creator_id)
    if not creator:
        raise HTTPException(404, "Creator not found")
    from workers.tasks import set_stop_flag, _log
    set_stop_flag(creator_id)
    _log(creator_id, "init", "warn", "Pipeline stopped by user")
    creator.status = "idle"
    creator.error_message = None
    await db.commit()


@router.post("/{creator_id}/reset", status_code=204)
async def reset_creator(creator_id: int, db: AsyncSession = Depends(get_db)):
    """Stop pipeline, delete all data, and delete the creator."""
    creator = await db.get(Creator, creator_id)
    if not creator:
        raise HTTPException(404, "Creator not found")

    from workers.tasks import set_stop_flag, clear_logs
    set_stop_flag(creator_id)

    posts = (await db.scalars(
        select(Post).where(Post.creator_id == creator_id)
    )).all()

    post_ids = [p.id for p in posts]
    if post_ids:
        await db.execute(delete(Comment).where(Comment.post_id.in_(post_ids)))

    for post in posts:
        if post.raw_data_path:
            try:
                Path(post.raw_data_path).unlink(missing_ok=True)
            except Exception:
                pass

    await db.execute(delete(Post).where(Post.creator_id == creator_id))
    clear_logs(creator_id)
    await db.delete(creator)
    await db.commit()


@router.delete("/{creator_id}", status_code=204)
async def delete_creator(creator_id: int, db: AsyncSession = Depends(get_db)):
    creator = await db.get(Creator, creator_id)
    if not creator:
        raise HTTPException(404, "Creator not found")
    await db.delete(creator)
    await db.commit()


@router.get("/{creator_id}/posts")
async def get_creator_posts(creator_id: int, db: AsyncSession = Depends(get_db)):
    posts = (await db.scalars(
        select(Post).where(Post.creator_id == creator_id).order_by(Post.scraped_at.desc())
    )).all()
    return [
        {
            "id": p.id,
            "url": p.url,
            "external_id": p.external_id,
            "likes": p.likes,
            "views": p.views,
            "comment_count": p.comment_count,
            "etl_status": p.etl_status,
            "scraped_at": p.scraped_at,
            "posted_at": p.posted_at,
            "caption": p.caption or "",
            "media_type": p.media_type or 1,
            "is_collab": bool(p.is_collab),
            "counts_disabled": bool(p.counts_disabled),
            "tags": __import__("json").loads(p.tags or "[]"),
            "thumbnail_url": p.thumbnail_url or "",
        }
        for p in posts
    ]


@router.get("/{creator_id}/posts/{post_id}/topics")
async def get_post_topics(creator_id: int, post_id: int, db: AsyncSession = Depends(get_db)):
    from app.models.comment import Comment
    from analytics.topics_engine import extract_topics_with_ai
    import asyncio
    from functools import partial

    post = await db.get(Post, post_id)
    if not post or post.creator_id != creator_id:
        raise HTTPException(404, "Post not found")

    comments = (await db.scalars(
        select(Comment).where(Comment.post_id == post_id)
    )).all()

    texts = [c.cleaned_text or c.raw_text for c in comments if c.cleaned_text or c.raw_text]
    if not texts:
        return {"topics": [], "comment_count": 0}

    loop = asyncio.get_running_loop()
    topics = await loop.run_in_executor(None, partial(extract_topics_with_ai, texts, 10))
    return {"topics": topics or [], "comment_count": len(texts)}


@router.post("/{creator_id}/posts/{post_id}/rescrape")
async def rescrape_post(creator_id: int, post_id: int, db: AsyncSession = Depends(get_db)):
    """Force re-scrape of a single post (resets status so comments are re-fetched)."""
    from workers.tasks import scrape_and_process_post
    from app.models.platform import Platform

    post = await db.get(Post, post_id)
    if not post or post.creator_id != creator_id:
        raise HTTPException(404, "Post not found")

    platform_obj = await db.get(Platform, post.platform_id)
    platform_name = platform_obj.name if platform_obj else "instagram"

    post.etl_status = "pending"
    await db.commit()

    task = scrape_and_process_post.delay(
        post.url, post.external_id, platform_name, creator_id, {
            "likes": post.likes, "views": post.views, "shares": post.shares,
            "comment_count": post.comment_count, "caption": post.caption or "",
            "tags": __import__("json").loads(post.tags or "[]"),
            "media_type": post.media_type or 1,
        }
    )
    return {"task_id": task.id, "post_id": post_id}


@router.get("/{creator_id}/posts/{post_id}/comments")
async def get_post_comments(
    creator_id: int,
    post_id: int,
    sentiment: str = Query(None),
    sort: str = Query("likes", enum=["likes", "date"]),
    limit: int = Query(100, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    post = await db.get(Post, post_id)
    if not post or post.creator_id != creator_id:
        raise HTTPException(404, "Post not found")

    q = select(Comment).where(Comment.post_id == post_id)
    if sentiment:
        q = q.where(Comment.sentiment == sentiment)
    order = Comment.likes.desc() if sort == "likes" else Comment.scraped_at.desc()
    q = q.order_by(order).offset(offset).limit(limit)

    comments = (await db.scalars(q)).all()
    count_q = select(func.count()).select_from(Comment).where(Comment.post_id == post_id)
    if sentiment:
        count_q = count_q.where(Comment.sentiment == sentiment)
    total = (await db.scalar(count_q))

    return {
        "total": total,
        "comments": [
            {
                "id": c.id,
                "author": c.author or "anonymous",
                "raw_text": c.raw_text,
                "likes": c.likes or 0,
                "sentiment": c.sentiment,
                "sentiment_score": c.sentiment_score,
                "posted_at": c.posted_at,
            }
            for c in comments
        ],
    }


@router.post("/{creator_id}/posts/{post_id}/summary")
async def summarize_post(creator_id: int, post_id: int, db: AsyncSession = Depends(get_db)):
    from app.models.comment import Comment
    from app.config import settings

    post = await db.get(Post, post_id)
    if not post or post.creator_id != creator_id:
        raise HTTPException(404, "Post not found")

    comments = (await db.scalars(
        select(Comment)
        .where(Comment.post_id == post_id)
        .order_by(Comment.likes.desc())
        .limit(25)
    )).all()

    media_label = {1: "Photo", 2: "Reel/Video", 8: "Carousel"}.get(post.media_type or 1, "Post")
    tags = __import__("json").loads(post.tags or "[]")
    tag_str = ", ".join(f"#{t}" for t in tags[:10]) if tags else "none"

    sentiment_summary = ""
    if comments:
        pos = sum(1 for c in comments if c.sentiment == "positive")
        neg = sum(1 for c in comments if c.sentiment == "negative")
        neu = sum(1 for c in comments if c.sentiment == "neutral")
        total = len(comments)
        sentiment_summary = f"Sentiment breakdown ({total} sample comments): {round(pos/total*100)}% positive, {round(neg/total*100)}% negative, {round(neu/total*100)}% neutral."
        sample_texts = [
            f'- [{c.sentiment or "?"}] "{(c.raw_text or "")[:120]}"'
            for c in comments[:10]
        ]
        comment_block = "\n".join(sample_texts)
    else:
        sentiment_summary = "No comments analyzed yet."
        comment_block = "(no comments)"

    if not getattr(settings, "GROQ_API_KEY", None):
        # Template fallback when no AI key
        caption_snippet = (post.caption or "")[:200] or "(no caption)"
        summary = (
            f"This {media_label} post"
            + (f" discusses: {caption_snippet}" if post.caption else " has no caption")
            + f" | Tags: {tag_str}"
            + f" | {post.likes or 0:,} likes, {post.views or 0:,} views, {post.comment_count or 0} comments."
            + f" {sentiment_summary}"
        )
        return {"summary": summary, "source": "template"}

    prompt = f"""You are an influencer analytics assistant for a Tunisian brand platform.

Post type: {media_label}
Caption: {(post.caption or "(no caption)")[:400]}
Hashtags: {tag_str}
Metrics: {post.likes or 0:,} likes · {post.views or 0:,} views · {post.comment_count or 0} comments
{sentiment_summary}

Sample comments:
{comment_block}

Write exactly 2 sentences in English:
1. What this post is about (topic, theme, product if identifiable).
2. How the audience reacted overall.
Be concise and data-driven. Do not add headers or bullet points."""

    try:
        from groq import Groq
        client = Groq(api_key=settings.GROQ_API_KEY)
        resp = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=200,
            temperature=0.4,
        )
        summary = resp.choices[0].message.content.strip()
        return {"summary": summary, "source": "ai"}
    except Exception as exc:
        raise HTTPException(503, f"AI summary unavailable: {exc}")


@router.get("/{creator_id}/comments")
async def get_creator_comments(
    creator_id: int,
    sentiment: str = Query(None),
    sort: str = Query("date", enum=["date", "likes"]),
    limit: int = Query(100, le=500),
    db: AsyncSession = Depends(get_db),
):
    post_ids = (await db.scalars(
        select(Post.id).where(Post.creator_id == creator_id)
    )).all()
    if not post_ids:
        return []
    q = select(Comment).where(Comment.post_id.in_(post_ids))
    if sentiment:
        q = q.where(Comment.sentiment == sentiment)
    order = Comment.likes.desc() if sort == "likes" else Comment.scraped_at.desc()
    q = q.order_by(order).limit(limit)
    comments = (await db.scalars(q)).all()
    return [
        {
            "id": c.id,
            "author": c.author,
            "raw_text": c.raw_text,
            "sentiment": c.sentiment,
            "sentiment_score": c.sentiment_score,
            "language": c.language,
            "likes": c.likes,
            "posted_at": c.posted_at.isoformat() if c.posted_at else None,
        }
        for c in comments
    ]


@router.get("/{creator_id}/top-comments")
async def get_top_comments(
    creator_id: int,
    limit: int = Query(10, le=50),
    db: AsyncSession = Depends(get_db),
):
    """Top comments by likes — the most impactful audience voices."""
    post_ids = (await db.scalars(
        select(Post.id).where(Post.creator_id == creator_id)
    )).all()
    if not post_ids:
        return []
    comments = (await db.scalars(
        select(Comment)
        .where(Comment.post_id.in_(post_ids), Comment.likes > 0)
        .order_by(Comment.likes.desc())
        .limit(limit)
    )).all()
    return [
        {
            "id": c.id,
            "author": c.author,
            "text": c.raw_text,
            "likes": c.likes,
            "sentiment": c.sentiment,
            "sentiment_score": c.sentiment_score,
            "posted_at": c.posted_at.isoformat() if c.posted_at else None,
        }
        for c in comments
    ]


def _default_url(platform: str, username: str) -> str:
    username = username.lstrip("@")
    return {
        "instagram": f"https://www.instagram.com/{username}/",
        "youtube":   f"https://www.youtube.com/@{username}/videos",
    }.get(platform, "")
