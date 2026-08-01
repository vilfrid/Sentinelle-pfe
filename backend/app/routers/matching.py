import asyncio
import json
import logging
import re

import redis as redis_lib
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List

from app.config import settings
from app.database import get_db
from app.schemas.influencer import MatchResult
from analytics.matching_engine import MatchingEngine, compute_and_cache_all, _CACHE_KEY, _CACHE_TTL
from analytics.embedding_service import EmbeddingService, _BGE_DIM
from app.models.creator import Creator
from app.models.campaign import Campaign
from app.models.post import Post
from app.models.platform import Platform

router = APIRouter()
logger = logging.getLogger(__name__)

_redis = redis_lib.from_url(settings.REDIS_URL, decode_responses=True)
_HTAG_RE = re.compile(r"#(\w+)")


def _embedding_needs_regen(raw_json: str, target_dim: int) -> bool:
    if not raw_json:
        return True
    try:
        vec = json.loads(raw_json)
        return len(vec) != target_dim
    except Exception:
        return True


# ── IMPORTANT: fixed-path routes MUST come before /{campaign_id} ─────────────
# FastAPI matches routes in registration order; "embedding-backend" would be
# captured as campaign_id (int) and raise 422 if this route were listed last.

@router.get("/embedding-backend")
def embedding_backend_status():
    """Returns which embedding backend is configured and reachable."""
    svc = EmbeddingService()
    bge_ready = False
    if svc._bge_url:
        bge_ready = svc._bge_ready()
    return {
        "bge_url":   svc._bge_url or None,
        "bge_ready": bge_ready,
        "active":    "bge-m3" if (svc._bge_url and bge_ready) else ("bge-m3 (sleeping)" if svc._bge_url else "none"),
        "dim":       _BGE_DIM if svc._bge_url else "?",
    }


@router.post("/refresh-all")
async def refresh_all_matches(db: AsyncSession = Depends(get_db)):
    refreshed = await compute_and_cache_all(_redis)
    return {"refreshed": refreshed}


@router.post("/compute-embeddings")
async def compute_embeddings(
    force: bool = Query(False, description="Regenerate all embeddings (use after switching model)"),
    db: AsyncSession = Depends(get_db),
):
    """
    Generate embeddings for campaigns and creators via the BGE Space
    (BAAI/bge-m3, 1024-dim).
    Use ?force=true to regenerate stale vectors after switching embedding models.
    """
    svc = EmbeddingService()
    if not svc._bge_url:
        return {"error": "BGE_SPACE_URL is not configured", "campaigns_updated": 0, "creators_updated": 0}
    stats = {
        "campaigns_updated": 0,
        "creators_updated": 0,
        "errors": [],
        "backend": "bge-m3",
        "dim": _BGE_DIM,
    }
    target_dim = _BGE_DIM
    loop = asyncio.get_running_loop()

    # ── Campaigns ─────────────────────────────────────────────────────────────
    campaigns = (await db.scalars(select(Campaign))).all()
    for campaign in campaigns:
        stored = getattr(campaign, "campaign_embedding", None)
        needs = force or (target_dim and _embedding_needs_regen(stored, target_dim)) or not stored
        if not needs:
            continue
        text = svc.build_campaign_text(
            campaign.name, campaign.brand, campaign.description, campaign.keywords or []
        )
        embedding = await loop.run_in_executor(None, svc.generate_embedding, text)
        if embedding:
            campaign.campaign_embedding = json.dumps(embedding)
            stats["campaigns_updated"] += 1
            logger.info("Campaign #%d embedded (%d dims)", campaign.id, len(embedding))
        else:
            stats["errors"].append(f"Campaign #{campaign.id}: embedding failed")

    # ── Creators — batched in one round-trip to BGE Space ────────────────────
    platforms = (await db.scalars(select(Platform))).all()
    platform_names = {p.id: p.name.lower() for p in platforms}

    creators = (await db.scalars(select(Creator))).all()
    all_posts_raw = (await db.scalars(select(Post))).all()
    posts_by_creator: dict = {}
    for p in all_posts_raw:
        posts_by_creator.setdefault(p.creator_id, []).append(p)

    to_embed: List[tuple] = []

    for creator in creators:
        stored = creator.content_embedding
        needs = force or (target_dim and _embedding_needs_regen(stored, target_dim)) or not stored
        if not needs:
            continue

        topic_names = [
            str(t.get("topic", "")) if isinstance(t, dict) else str(t)
            for t in (creator.top_topics or [])
        ]

        posts = posts_by_creator.get(creator.id, [])
        n = len(posts)
        avg_views  = sum(p.views  or 0 for p in posts) / n if n else 0.0
        avg_likes  = sum(p.likes  or 0 for p in posts) / n if n else 0.0
        avg_cmts   = sum(p.comment_count or 0 for p in posts) / n if n else 0.0
        avg_shares = sum(p.shares or 0 for p in posts) / n if n else 0.0
        if avg_views > 0:
            eng_rate = min((avg_likes + avg_cmts) / avg_views * 100, 100.0)
        elif avg_likes > 0:
            eng_rate = min(avg_cmts / avg_likes * 100, 20.0)
        else:
            eng_rate = 0.0

        ht_counts: dict = {}
        for p in posts:
            for h in _HTAG_RE.findall(p.caption or ""):
                ht_counts[h.lower()] = ht_counts.get(h.lower(), 0) + 1
        top_hashtags = [h for h, _ in sorted(ht_counts.items(), key=lambda x: -x[1])[:12]]

        text = svc.build_creator_text(
            creator.username, creator.bio, topic_names, creator.audience_mood,
            hashtags=top_hashtags,
            platform=platform_names.get(creator.platform_id, "unknown"),
            follower_count=creator.follower_count or 0,
            avg_views=avg_views,
            avg_shares=avg_shares,
            engagement_rate=eng_rate,
        )
        to_embed.append((creator, text))

    if to_embed:
        texts = [t for _, t in to_embed]
        logger.info("Batch-embedding %d creators via %s …", len(texts), stats["backend"])
        embeddings = await loop.run_in_executor(None, svc.generate_embeddings_batch, texts)

        for (creator, text), embedding in zip(to_embed, embeddings):
            if embedding:
                creator.content_summary = text
                creator.content_embedding = json.dumps(embedding)
                stats["creators_updated"] += 1
            else:
                stats["errors"].append(f"Creator #{creator.id} (@{creator.username}): embedding failed")

    await db.commit()

    if stats["campaigns_updated"] + stats["creators_updated"] > 0:
        await compute_and_cache_all(_redis)

    return stats


# ── campaign_id route LAST so fixed paths above are matched first ─────────────
@router.get("/{campaign_id}", response_model=List[MatchResult])
async def match_creators(
    campaign_id: int,
    top_k: int = Query(10, ge=1, le=50),
    refresh: bool = Query(False),
    db: AsyncSession = Depends(get_db),
):
    cache_key = _CACHE_KEY.format(campaign_id)
    if not refresh:
        cached = _redis.get(cache_key)
        if cached:
            try:
                return json.loads(cached)[:top_k]
            except Exception:
                pass
    engine = MatchingEngine(db)
    results = await engine.match(campaign_id, top_k=50)
    if results:
        _redis.setex(cache_key, _CACHE_TTL, json.dumps(results))
    return results[:top_k]
