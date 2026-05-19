from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List, Optional

from app.database import get_db
from app.models.comment import Comment
from app.models.post import Post
from app.schemas.comment import CommentOut

router = APIRouter()


@router.get("/", response_model=List[CommentOut])
async def list_comments(
    campaign_id: Optional[int] = Query(None),
    sentiment: Optional[str] = Query(None),
    sort: str = Query("date", enum=["date", "likes"]),
    limit: int = Query(200, le=1000),
    offset: int = Query(0),
    db: AsyncSession = Depends(get_db),
):
    q = select(Comment)
    if campaign_id:
        post_ids = (await db.scalars(
            select(Post.id).where(Post.campaign_id == campaign_id)
        )).all()
        q = q.where(Comment.post_id.in_(post_ids))
    if sentiment:
        q = q.where(Comment.sentiment == sentiment)
    order = Comment.likes.desc() if sort == "likes" else Comment.scraped_at.desc()
    q = q.order_by(order).offset(offset).limit(limit)
    result = await db.scalars(q)
    return result.all()
