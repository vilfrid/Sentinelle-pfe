from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime


class CampaignCreate(BaseModel):
    name: str
    brand: str
    description: Optional[str] = None
    keywords: List[str] = []
    target_platforms: List[str] = []


class CampaignUpdate(BaseModel):
    name: Optional[str] = None
    brand: Optional[str] = None
    description: Optional[str] = None
    keywords: Optional[List[str]] = None
    target_platforms: Optional[List[str]] = None
    status: Optional[str] = None


class CampaignOut(BaseModel):
    id: int
    name: str
    brand: str
    description: Optional[str]
    keywords: List[str]
    target_platforms: List[str]
    status: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
