from pydantic import BaseModel
from typing import List, Optional, Dict


class MatchCreatorOut(BaseModel):
    id: int
    username: str
    display_name: Optional[str] = None
    bio: Optional[str] = None
    profile_url: Optional[str] = None
    avatar_url: Optional[str] = None
    follower_count: int = 0
    total_comments: int = 0
    positive_pct: float = 0.0
    negative_pct: float = 0.0
    neutral_pct: float = 0.0
    audience_mood: Optional[str] = None
    content_topics: List[str] = []
    has_embedding: bool = False
    campaign_id: Optional[int] = None
    influencer_tier: str = "unknown"
    platform: Optional[str] = None
    # Post-level signals
    post_count: int = 0
    avg_views: int = 0
    avg_likes: int = 0
    avg_shares: int = 0
    avg_comments_per_post: int = 0
    engagement_rate: float = 0.0
    share_rate: float = 0.0          # avg_shares / reach_proxy × 100 (%)
    top_hashtags: List[str] = []
    authenticity_score: float = 0.5
    estimated_reach: int = 0
    content_type_mix: Dict[str, int] = {}   # {video: %, photo: %, carousel: %}


class ScoreBreakdown(BaseModel):
    semantic: float = 0.0
    niche: float = 0.0
    audience: float = 0.0
    reach: float = 0.0
    brand_safety: float = 0.0
    recency: float = 0.0
    # Niche sub-scores
    topic_overlap: float = 0.0
    hashtag_overlap: float = 0.0
    caption_density: float = 0.0
    bio_match: float = 0.0          # new: bio keyword alignment
    # Audience sub-scores
    engagement_score: float = 0.0
    authenticity: float = 0.0
    comment_depth: float = 0.0
    virality: float = 0.0           # new: share-rate signal
    # True when niche was boosted by the semantic floor
    niche_from_semantic: bool = False


class MatchResult(BaseModel):
    creator: MatchCreatorOut
    match_score: float
    score_breakdown: ScoreBreakdown
    method: str
    matching_topics: List[str] = []
    matching_hashtags: List[str] = []
    reasoning: str
    estimated_reach: int = 0
    influencer_tier: str = "unknown"
    platform: Optional[str] = None
