from sqlalchemy import Column, Integer, String, DateTime, Float, ForeignKey, JSON, Text
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
from app.database import Base


class Influencer(Base):
    __tablename__ = "influencers"

    id = Column(Integer, primary_key=True, index=True)
    platform_id = Column(Integer, ForeignKey("platforms.id"), nullable=False)
    username = Column(String(200), nullable=False)
    display_name = Column(String(300))
    bio = Column(Text)
    profile_url = Column(String(1000))
    follower_count = Column(Integer, default=0)
    avg_engagement_rate = Column(Float, default=0.0)

    # Content profile (for vector matching)
    content_topics = Column(JSON, default=list)         # inferred topics
    content_embedding = Column(Text)                    # JSON-serialized vector
    dominant_language = Column(String(20))
    audience_sentiment_profile = Column(JSON, default=dict)

    # Match scores (updated per campaign query)
    last_match_score = Column(Float)
    last_matched_campaign_id = Column(Integer, ForeignKey("campaigns.id"))

    scraped_at = Column(DateTime, default=lambda: datetime.utcnow())

    platform = relationship("Platform", back_populates="influencers")
