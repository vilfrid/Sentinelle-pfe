import json
import logging
import re
import google.generativeai as genai
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List

from app.database import get_db
from app.models.campaign import Campaign
from app.schemas.campaign import CampaignCreate, CampaignOut, CampaignUpdate
from app.config import settings

router = APIRouter()
logger = logging.getLogger(__name__)


def generate_keywords(
    name: str,
    brand: str,
    description: str,
    trending_topics: List[str] | None = None,
    target_platforms: List[str] | None = None,
) -> List[str]:
    try:
        genai.configure(api_key=settings.GOOGLE_API_KEY)
        model = genai.GenerativeModel("gemini-2.5-flash")

        topics_line = ""
        if trending_topics:
            topics_line = f"Already-detected trending topics in comments: {', '.join(trending_topics[:15])}\n"

        platforms_line = ""
        if target_platforms:
            platforms_line = f"Target platforms: {', '.join(target_platforms)}\n"

        prompt = f"""You are a social media marketing expert specializing in the Tunisian and North-African market.
Generate 8 to 12 highly relevant tracking keywords and hashtags for this brand campaign.

Campaign name: {name}
Brand: {brand}
Description: {description or '(none)'}
{topics_line}{platforms_line}
Rules:
- Include a mix of: brand-specific terms, product/service category words, relevant Arabic/Darija/French terms used in Tunisia, and key hashtags (#...).
- Prioritize words that real Tunisian social media users would write in comments or hashtags.
- Do NOT include generic stop-words (and, the, des, les, في, من...).
- Return ONLY a raw JSON array of strings, no markdown, no explanation.

Example output: ["sneakers", "chaussures", "كوتشي", "#Nike", "collection2025", "mode"]
"""
        response = model.generate_content(prompt)
        text = re.sub(r"```(?:json)?\s*|\s*```", "", response.text).strip()
        parsed = json.loads(text)
        # Gemini sometimes wraps the array in an object — unwrap it
        if isinstance(parsed, dict):
            for key in ("keywords", "tags", "items", "results"):
                if key in parsed and isinstance(parsed[key], list):
                    parsed = parsed[key]
                    break
        if isinstance(parsed, list) and parsed:
            return [str(k).strip() for k in parsed if k]
        logger.warning("generate_keywords: unexpected response shape: %s", str(parsed)[:200])
    except Exception as e:
        logger.error("generate_keywords failed: %s", e)
    return []


@router.post("/suggest-new")
async def suggest_new_keywords(payload: dict):
    """
    Suggest keywords for a campaign that hasn't been created yet.
    Accepts {name, brand, description, target_platforms} in the body.
    Returns {"keywords": [...]} without persisting anything.
    """
    kws = generate_keywords(
        name=payload.get("name", ""),
        brand=payload.get("brand", ""),
        description=payload.get("description", ""),
        target_platforms=payload.get("target_platforms") or None,
    )
    return {"keywords": kws}


@router.get("/", response_model=List[CampaignOut])
async def list_campaigns(db: AsyncSession = Depends(get_db)):
    result = await db.scalars(select(Campaign).order_by(Campaign.created_at.desc()))
    return result.all()


@router.post("/", response_model=CampaignOut, status_code=201)
async def create_campaign(payload: CampaignCreate, db: AsyncSession = Depends(get_db)):
    data = payload.model_dump()

    if not data.get("keywords") and data.get("brand"):
        auto_kws = generate_keywords(
            name=data.get("name", ""),
            brand=data["brand"],
            description=data.get("description", ""),
            target_platforms=data.get("target_platforms"),
        )
        if auto_kws:
            data["keywords"] = auto_kws

    campaign = Campaign(**data)
    db.add(campaign)
    await db.commit()
    await db.refresh(campaign)
    return campaign


@router.get("/{campaign_id}", response_model=CampaignOut)
async def get_campaign(campaign_id: int, db: AsyncSession = Depends(get_db)):
    campaign = await db.get(Campaign, campaign_id)
    if not campaign:
        raise HTTPException(404, "Campaign not found")
    return campaign


@router.patch("/{campaign_id}", response_model=CampaignOut)
async def update_campaign(campaign_id: int, payload: CampaignUpdate, db: AsyncSession = Depends(get_db)):
    campaign = await db.get(Campaign, campaign_id)
    if not campaign:
        raise HTTPException(404, "Campaign not found")
    for field, value in payload.model_dump(exclude_none=True).items():
        setattr(campaign, field, value)
    await db.commit()
    await db.refresh(campaign)
    return campaign


@router.post("/{campaign_id}/suggest-keywords")
async def suggest_keywords(campaign_id: int, db: AsyncSession = Depends(get_db)):
    """
    Use Gemini to suggest keywords for an existing campaign.
    Uses already-stored creator top_topics (no extra AI call) as context.
    Does NOT save automatically — call PATCH /{id} to apply.
    """
    campaign = await db.get(Campaign, campaign_id)
    if not campaign:
        raise HTTPException(404, "Campaign not found")

    # Collect already-computed topics from creators linked to this campaign
    # (stored by the pipeline in creator.top_topics — no extra Gemini call needed)
    trending: List[str] = []
    try:
        from app.models.creator import Creator as CreatorModel
        creators = (await db.scalars(
            select(CreatorModel).where(CreatorModel.campaign_id == campaign_id)
        )).all()
        seen: set = set()
        for cr in creators:
            if not cr.top_topics:
                continue
            for t in cr.top_topics:
                topic = t.get("topic") if isinstance(t, dict) else str(t)
                if topic and topic not in seen:
                    seen.add(topic)
                    trending.append(topic)
                if len(trending) >= 20:
                    break
    except Exception as exc:
        logger.warning("Could not read creator topics for keyword suggestion: %s", exc)

    keywords = generate_keywords(
        name=campaign.name,
        brand=campaign.brand,
        description=campaign.description or "",
        trending_topics=trending or None,
        target_platforms=campaign.target_platforms or None,
    )

    return {"keywords": keywords, "trending_topics_used": trending}


@router.delete("/{campaign_id}", status_code=204)
async def delete_campaign(campaign_id: int, db: AsyncSession = Depends(get_db)):
    campaign = await db.get(Campaign, campaign_id)
    if not campaign:
        raise HTTPException(404, "Campaign not found")
        
    from sqlalchemy import update, delete
    from app.models.creator import Creator
    from app.models.post import Post
    from app.models.metric import Metric
    from app.models.report import Report
    
    # Unlink creators and posts instead of deleting them
    await db.execute(update(Creator).where(Creator.campaign_id == campaign_id).values(campaign_id=None))
    await db.execute(update(Post).where(Post.campaign_id == campaign_id).values(campaign_id=None))
    
    # Delete metrics and reports
    await db.execute(delete(Metric).where(Metric.campaign_id == campaign_id))
    await db.execute(delete(Report).where(Report.campaign_id == campaign_id))

    await db.delete(campaign)
    await db.commit()
