from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List

from app.database import get_db
from app.schemas.influencer import MatchResult
from analytics.matching_engine import MatchingEngine

router = APIRouter()


@router.get("/{campaign_id}", response_model=List[MatchResult])
async def match_influencers(
    campaign_id: int,
    top_k: int = Query(10, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
):
    engine = MatchingEngine(db)
    results = await engine.match(campaign_id, top_k=top_k)
    if not results:
        raise HTTPException(404, "No influencers found or campaign does not exist")
    return results
