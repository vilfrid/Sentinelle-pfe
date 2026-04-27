import json
import redis as redis_lib
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.database import get_db
from app.models.creator import Creator
from app.models.post import Post
from app.models.comment import Comment
from app.models.platform import Platform
from app.config import settings

router = APIRouter()
_redis = redis_lib.from_url(settings.REDIS_URL, decode_responses=True)


@router.get("/status")
async def pipeline_status(db: AsyncSession = Depends(get_db)):
    creators = (await db.scalars(
        select(Creator).order_by(Creator.created_at.desc())
    )).all()

    total_posts = await db.scalar(select(func.count(Post.id))) or 0
    total_comments = await db.scalar(select(func.count(Comment.id))) or 0

    by_status: dict = {}
    for c in creators:
        by_status[c.status] = by_status.get(c.status, 0) + 1

    creator_list = []
    for c in creators:
        platform = await db.get(Platform, c.platform_id)
        posts = (await db.scalars(
            select(Post).where(Post.creator_id == c.id).order_by(Post.scraped_at.desc())
        )).all()

        etl_breakdown: dict = {}
        for p in posts:
            etl_breakdown[p.etl_status] = etl_breakdown.get(p.etl_status, 0) + 1

        creator_list.append({
            "id": c.id,
            "username": c.username,
            "platform": platform.name if platform else "unknown",
            "status": c.status,
            "error": c.error_message,
            "total_posts": len(posts),
            "total_comments": c.total_comments,
            "etl_breakdown": etl_breakdown,
            "last_run": c.last_pipeline_at.isoformat() if c.last_pipeline_at else None,
            "task_id": c.pipeline_task_id,
        })

    return {
        "stats": {
            "total_creators": len(creators),
            "total_posts": total_posts,
            "total_comments": total_comments,
            "by_status": by_status,
        },
        "creators": creator_list,
    }


@router.get("/logs/{creator_id}")
async def get_creator_logs(creator_id: int):
    raw = _redis.lrange(f"pipeline:logs:{creator_id}", 0, -1)
    return [json.loads(e) for e in raw]
