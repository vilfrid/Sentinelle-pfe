from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List

from app.database import get_db
from app.models.campaign import Campaign
from app.schemas.campaign import CampaignCreate, CampaignOut, CampaignUpdate

router = APIRouter()


@router.get("/", response_model=List[CampaignOut])
async def list_campaigns(db: AsyncSession = Depends(get_db)):
    result = await db.scalars(select(Campaign).order_by(Campaign.created_at.desc()))
    return result.all()


@router.post("/", response_model=CampaignOut, status_code=201)
async def create_campaign(payload: CampaignCreate, db: AsyncSession = Depends(get_db)):
    campaign = Campaign(**payload.model_dump())
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


@router.delete("/{campaign_id}", status_code=204)
async def delete_campaign(campaign_id: int, db: AsyncSession = Depends(get_db)):
    campaign = await db.get(Campaign, campaign_id)
    if not campaign:
        raise HTTPException(404, "Campaign not found")
    await db.delete(campaign)
    await db.commit()
