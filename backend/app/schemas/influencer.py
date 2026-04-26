from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from datetime import datetime


class InfluencerOut(BaseModel):
    id: int
    username: str
    display_name: Optional[str]
    bio: Optional[str]
    profile_url: Optional[str]
    follower_count: int
    avg_engagement_rate: float
    content_topics: List[str]
    dominant_language: Optional[str]

    class Config:
        from_attributes = True


class MatchResult(BaseModel):
    influencer: InfluencerOut
    match_score: float
    matching_topics: List[str]
    reasoning: str
