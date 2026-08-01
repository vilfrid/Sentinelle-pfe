from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from datetime import datetime


class ReportCreate(BaseModel):
    campaign_id: int
    title: str
    period_start: Optional[datetime] = None
    period_end: Optional[datetime] = None


class ReportOut(BaseModel):
    id: int
    campaign_id: int
    title: str
    period_start: Optional[datetime]
    period_end: Optional[datetime]
    summary: Optional[str]
    what_worked: List[str]
    what_to_improve: List[str]
    recommendations: List[str]
    risk_alerts: Optional[List[str]] = []
    audience_insights: Optional[List[str]] = []
    trending_now: Optional[List[str]] = []
    fading_content: Optional[List[str]] = []
    content_strategy: Optional[List[str]] = []
    metrics_snapshot: Dict[str, Any]
    status: str
    created_at: datetime

    class Config:
        from_attributes = True
