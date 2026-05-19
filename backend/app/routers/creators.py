from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
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


@router.get("/{creator_id}", response_model=CreatorOut)
async def get_creator(creator_id: int, db: AsyncSession = Depends(get_db)):
    creator = await db.get(Creator, creator_id)
    if not creator:
        raise HTTPException(404, "Creator not found")
    return creator


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
        }
        for p in posts
    ]


@router.get("/{creator_id}/comments")
async def get_creator_comments(
    creator_id: int,
    sentiment: str = Query(None),
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
    q = q.order_by(Comment.scraped_at.desc()).limit(limit)
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
        }
        for c in comments
    ]


def _default_url(platform: str, username: str) -> str:
    username = username.lstrip("@")
    return {
        "instagram": f"https://www.instagram.com/{username}/",
        "tiktok": f"https://www.tiktok.com/@{username}",
        "youtube": f"https://www.youtube.com/@{username}/videos",
    }.get(platform, "")
