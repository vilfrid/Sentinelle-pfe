from sqlalchemy import Column, Integer, String, DateTime, Text, JSON
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
from app.database import Base


class Campaign(Base):
    __tablename__ = "campaigns"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(200), nullable=False)
    brand = Column(String(200), nullable=False)
    description = Column(Text)
    keywords = Column(JSON, default=list)   # tracked keywords/hashtags
    target_platforms = Column(JSON, default=list)
    status = Column(String(50), default="active")  # active, paused, completed
    campaign_embedding = Column(Text)                # JSON-serialized embedding vector
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    posts = relationship("Post", back_populates="campaign")
    metrics = relationship("Metric", back_populates="campaign")
    reports = relationship("Report", back_populates="campaign")
