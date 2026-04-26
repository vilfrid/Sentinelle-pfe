from sqlalchemy import Column, Integer, String, DateTime, Text, ForeignKey, JSON
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
from app.database import Base


class Report(Base):
    __tablename__ = "reports"

    id = Column(Integer, primary_key=True, index=True)
    campaign_id = Column(Integer, ForeignKey("campaigns.id"), nullable=False)
    title = Column(String(300), nullable=False)
    period_start = Column(DateTime)
    period_end = Column(DateTime)

    # AI-generated insights
    summary = Column(Text)
    what_worked = Column(JSON, default=list)        # list of positive insights
    what_to_improve = Column(JSON, default=list)    # list of improvement points
    recommendations = Column(JSON, default=list)

    # Snapshot of key metrics at time of generation
    metrics_snapshot = Column(JSON, default=dict)

    status = Column(String(50), default="draft")    # draft, published
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    campaign = relationship("Campaign", back_populates="reports")
