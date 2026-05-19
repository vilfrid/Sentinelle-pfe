"""
Brand-Creator matching using embedding cosine similarity.
Uses Google text-embedding-004 vectors stored on Creator and Campaign records.
Falls back to keyword overlap when embeddings are not available.

Composite final score = 0.75 * semantic_score + 0.15 * sentiment_bonus + 0.10 * engagement_bonus
"""
import json
import logging
import math
from typing import List, Tuple, Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.creator import Creator
from app.models.campaign import Campaign

logger = logging.getLogger(__name__)

_MIN_SCORE = 0.05          # drop creators with near-zero relevance
_SEMANTIC_WEIGHT = 0.75
_SENTIMENT_WEIGHT = 0.15
_ENGAGEMENT_WEIGHT = 0.10
_MAX_FOLLOWER_LOG = math.log1p(1_000_000)  # normalise log(followers) to [0,1]


def _cosine(v1: List[float], v2: List[float]) -> float:
    dot = sum(a * b for a, b in zip(v1, v2))
    mag1 = math.sqrt(sum(a * a for a in v1))
    mag2 = math.sqrt(sum(b * b for b in v2))
    if mag1 == 0 or mag2 == 0:
        return 0.0
    return dot / (mag1 * mag2)


def _keyword_score(brand_kw: List[str], creator_topics: List[str]) -> float:
    """Jaccard overlap between campaign keywords and creator topics."""
    if not brand_kw or not creator_topics:
        return 0.0
    brand_set = {k.lower() for k in brand_kw}
    creator_set = {t.lower() if isinstance(t, str) else str(t).lower() for t in creator_topics}
    overlap = brand_set & creator_set
    union = brand_set | creator_set
    return len(overlap) / max(len(union), 1)


def _sentiment_bonus(creator: Creator) -> float:
    """0–1 score rewarding creators with high positive audience sentiment."""
    pos = creator.positive_pct or 0.0
    neg = creator.negative_pct or 0.0
    # (positive - negative) mapped from [-100, 100] → [0, 1]
    return (pos - neg + 100) / 200.0


def _engagement_bonus(creator: Creator) -> float:
    """0–1 score based on log(follower_count) as a proxy for reach."""
    followers = creator.follower_count or 0
    if followers <= 0:
        return 0.0
    return min(math.log1p(followers) / _MAX_FOLLOWER_LOG, 1.0)


class MatchingEngine:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def match(self, campaign_id: int, top_k: int = 10) -> List[dict]:
        """
        Match a campaign against all creators.
        Returns top_k by composite score; filters out scores below _MIN_SCORE.
        """
        campaign = await self.db.get(Campaign, campaign_id)
        if not campaign:
            return []

        creators = (await self.db.scalars(select(Creator))).all()
        if not creators:
            return []

        campaign_embedding = self._load_embedding(campaign, "campaign")

        scored: List[Tuple[float, float, Creator, str, List[str]]] = []

        for creator in creators:
            creator_embedding = self._load_creator_embedding(creator)
            topic_names = self._extract_topic_names(creator.top_topics)
            brand_keywords = campaign.keywords or []

            if campaign_embedding and creator_embedding:
                semantic = _cosine(campaign_embedding, creator_embedding)
                method = "embedding"
            else:
                semantic = _keyword_score(brand_keywords, topic_names)
                method = "keyword"

            composite = (
                _SEMANTIC_WEIGHT * semantic
                + _SENTIMENT_WEIGHT * _sentiment_bonus(creator)
                + _ENGAGEMENT_WEIGHT * _engagement_bonus(creator)
            )

            if composite < _MIN_SCORE:
                continue

            brand_set = {k.lower() for k in brand_keywords}
            creator_set = {t.lower() for t in topic_names}
            shared = list(brand_set & creator_set)

            scored.append((composite, semantic, creator, method, shared))

        scored.sort(key=lambda x: x[0], reverse=True)

        results = []
        for composite, semantic, creator, method, shared in scored[:top_k]:
            topic_names = self._extract_topic_names(creator.top_topics)
            results.append({
                "creator": {
                    "id": creator.id,
                    "username": creator.username,
                    "display_name": creator.display_name,
                    "bio": creator.bio,
                    "profile_url": creator.profile_url,
                    "follower_count": creator.follower_count or 0,
                    "total_comments": creator.total_comments or 0,
                    "positive_pct": creator.positive_pct or 0.0,
                    "negative_pct": creator.negative_pct or 0.0,
                    "audience_mood": creator.audience_mood,
                    "content_topics": topic_names,
                    "has_embedding": creator.content_embedding is not None,
                    "campaign_id": creator.campaign_id,
                },
                "match_score": round(composite, 4),
                "matching_topics": shared,
                "method": method,
                "reasoning": self._build_reasoning(composite, semantic, method, shared, creator),
            })

        return results

    def _load_embedding(self, obj, obj_type: str) -> Optional[List[float]]:
        raw = getattr(obj, "campaign_embedding", None)
        if not raw:
            return None
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            logger.warning("Failed to parse %s embedding", obj_type)
            return None

    def _load_creator_embedding(self, creator: Creator) -> Optional[List[float]]:
        if not creator.content_embedding:
            return None
        try:
            return json.loads(creator.content_embedding)
        except (json.JSONDecodeError, TypeError):
            return None

    def _extract_topic_names(self, top_topics) -> List[str]:
        if not top_topics:
            return []
        names = []
        for t in top_topics:
            if isinstance(t, dict):
                names.append(str(t.get("topic", "")))
            elif isinstance(t, str):
                names.append(t)
        return [n for n in names if n]

    def _build_reasoning(
        self,
        composite: float,
        semantic: float,
        method: str,
        shared: List[str],
        creator: Creator,
    ) -> str:
        parts = []
        if method == "embedding":
            parts.append(f"Semantic similarity: {semantic:.1%}")
        else:
            parts.append(f"Keyword overlap: {semantic:.1%}")

        sent_b = _sentiment_bonus(creator)
        if sent_b > 0.6:
            parts.append(f"Positive audience ({creator.positive_pct:.0f}% pos)")
        elif sent_b < 0.4:
            parts.append(f"Caution: {creator.negative_pct:.0f}% negative sentiment")

        followers = creator.follower_count or 0
        if followers > 0:
            if followers >= 1_000_000:
                reach = f"{followers/1_000_000:.1f}M followers"
            elif followers >= 1_000:
                reach = f"{followers/1_000:.0f}K followers"
            else:
                reach = f"{followers} followers"
            parts.append(reach)

        if shared:
            parts.append(f"Shared topics: {', '.join(shared[:5])}")

        if creator.total_comments and creator.total_comments > 0:
            parts.append(f"{creator.total_comments} comments analyzed")

        return " · ".join(parts)
