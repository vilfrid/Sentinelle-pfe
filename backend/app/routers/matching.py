from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List
import json

from app.database import get_db
from app.schemas.influencer import MatchResult
from analytics.matching_engine import MatchingEngine
from analytics.embedding_service import EmbeddingService
from app.models.creator import Creator
from app.models.campaign import Campaign

router = APIRouter()


@router.get("/{campaign_id}", response_model=List[MatchResult])
async def match_creators(
    campaign_id: int,
    top_k: int = Query(10, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
):
    """Match a campaign against all creators using embedding similarity."""
    engine = MatchingEngine(db)
    results = await engine.match(campaign_id, top_k=top_k)
    return results


@router.post("/compute-embeddings")
async def compute_embeddings(db: AsyncSession = Depends(get_db)):
    """
    Generate embeddings for all campaigns and creators that don't have one yet.
    Uses Google text-embedding-004 model.
    """
    svc = EmbeddingService()
    stats = {"campaigns_updated": 0, "creators_updated": 0, "errors": []}

    # ── Campaigns ──
    campaigns = (await db.scalars(select(Campaign))).all()
    for campaign in campaigns:
        if getattr(campaign, "campaign_embedding", None):
            continue
        text = svc.build_campaign_text(
            campaign.name, campaign.brand, campaign.description, campaign.keywords or []
        )
        embedding = svc.generate_embedding(text)
        if embedding:
            campaign.campaign_embedding = json.dumps(embedding)
            stats["campaigns_updated"] += 1
        else:
            stats["errors"].append(f"Campaign #{campaign.id}: embedding failed")

    # ── Creators ──
    creators = (await db.scalars(select(Creator))).all()
    for creator in creators:
        if creator.content_embedding:
            continue
        topic_names = []
        if creator.top_topics:
            for t in creator.top_topics:
                if isinstance(t, dict):
                    topic_names.append(str(t.get("topic", "")))
                elif isinstance(t, str):
                    topic_names.append(t)

        text = svc.build_creator_text(
            creator.username, creator.bio, topic_names, creator.audience_mood
        )
        embedding = svc.generate_embedding(text)
        if embedding:
            creator.content_summary = text
            creator.content_embedding = json.dumps(embedding)
            stats["creators_updated"] += 1
        else:
            stats["errors"].append(f"Creator #{creator.id}: embedding failed")

    await db.commit()
    return stats
