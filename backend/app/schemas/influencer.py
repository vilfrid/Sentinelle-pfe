from pydantic import BaseModel
from typing import List, Optional, Dict, Any


class MatchCreatorOut(BaseModel):
    id: int
    username: str
    display_name: Optional[str] = None
    bio: Optional[str] = None
    profile_url: Optional[str] = None
    follower_count: int = 0
    total_comments: int = 0
    positive_pct: float = 0.0
    negative_pct: float = 0.0
    audience_mood: Optional[str] = None
    content_topics: List[str] = []
    has_embedding: bool = False


class MatchResult(BaseModel):
    creator: MatchCreatorOut
    match_score: float
    matching_topics: List[str]
    method: str          # "embedding" or "keyword"
    reasoning: str
