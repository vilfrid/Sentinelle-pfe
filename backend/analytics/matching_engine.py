"""
Brand-Influencer matching using cosine similarity on topic vectors.
"""
import json
import logging
import math
from typing import List, Tuple

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.influencer import Influencer
from app.models.campaign import Campaign
from app.schemas.influencer import InfluencerOut, MatchResult

logger = logging.getLogger(__name__)


def _cosine(v1: List[float], v2: List[float]) -> float:
    dot = sum(a * b for a, b in zip(v1, v2))
    mag1 = math.sqrt(sum(a * a for a in v1))
    mag2 = math.sqrt(sum(b * b for b in v2))
    if mag1 == 0 or mag2 == 0:
        return 0.0
    return dot / (mag1 * mag2)


def _topic_vector(topics: List[str], vocab: List[str]) -> List[float]:
    s = set(t.lower() for t in topics)
    return [1.0 if v.lower() in s else 0.0 for v in vocab]


class MatchingEngine:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def match(self, campaign_id: int, top_k: int = 10) -> List[MatchResult]:
        campaign = await self.db.get(Campaign, campaign_id)
        if not campaign:
            return []

        brand_topics: List[str] = campaign.keywords or []

        influencers = (await self.db.scalars(select(Influencer))).all()
        if not influencers:
            return []

        # Build shared vocabulary from brand + all influencer topics
        vocab: set = set(t.lower() for t in brand_topics)
        for inf in influencers:
            vocab.update(t.lower() for t in (inf.content_topics or []))
        vocab_list = sorted(vocab)

        brand_vec = _topic_vector(brand_topics, vocab_list)
        scored: List[Tuple[float, Influencer]] = []

        for inf in influencers:
            inf_vec = _topic_vector(inf.content_topics or [], vocab_list)
            score = _cosine(brand_vec, inf_vec)
            scored.append((score, inf))

        scored.sort(key=lambda x: x[0], reverse=True)
        results = []
        for score, inf in scored[:top_k]:
            brand_set = {t.lower() for t in brand_topics}
            inf_set = {t.lower() for t in (inf.content_topics or [])}
            shared = list(brand_set & inf_set)
            results.append(
                MatchResult(
                    influencer=InfluencerOut.model_validate(inf),
                    match_score=round(score, 4),
                    matching_topics=shared,
                    reasoning=f"Shares {len(shared)} topic(s) with campaign keywords",
                )
            )
        return results
