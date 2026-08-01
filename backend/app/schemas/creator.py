from pydantic import BaseModel, field_validator
from typing import Optional, List, Any
from datetime import datetime


class CreatorCreate(BaseModel):
    username: str
    platform: str          # instagram | youtube
    campaign_id: Optional[int] = None
    profile_url: Optional[str] = None


class CreatorUpdate(BaseModel):
    campaign_id: Optional[int] = None


class CreatorOut(BaseModel):
    id: int
    username: str
    display_name: Optional[str]
    profile_url: Optional[str]
    bio: Optional[str]
    follower_count: int
    avatar_url: Optional[str]
    status: str
    pipeline_task_id: Optional[str]
    error_message: Optional[str]
    last_pipeline_at: Optional[datetime]
    total_posts_scraped: int
    total_comments: int
    positive_pct: float
    negative_pct: float
    neutral_pct: float
    avg_sentiment_score: float
    top_topics: List[Any] = []
    audience_mood: Optional[str]
    campaign_id: Optional[int]
    created_at: datetime
    avg_views: int = 0
    avg_likes: int = 0
    avg_shares: int = 0

    @field_validator("top_topics", mode="before")
    @classmethod
    def _coerce_topics(cls, v: Any) -> list:
        return v if isinstance(v, list) else []

    class Config:
        from_attributes = True
