from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from datetime import datetime


class MetricOut(BaseModel):
    id: int
    campaign_id: int
    period: str
    period_start: datetime
    period_end: datetime
    total_comments: int
    total_posts: int
    positive_count: int
    negative_count: int
    neutral_count: int
    avg_sentiment_score: float
    impression_score: float
    virality_score: float
    engagement_rate: float
    audience_mood: Optional[str]
    mood_shift: float
    trending_topics: List[Dict[str, Any]]
    top_keywords: List[Any]
    negative_spike: int
    computed_at: datetime

    class Config:
        from_attributes = True
