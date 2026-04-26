from sqlalchemy import Column, Integer, String, DateTime, Float, ForeignKey, JSON, Text
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
from app.database import Base


class Creator(Base):
    __tablename__ = "creators"

    id = Column(Integer, primary_key=True, index=True)
    platform_id = Column(Integer, ForeignKey("platforms.id"), nullable=False)
    campaign_id = Column(Integer, ForeignKey("campaigns.id"), nullable=True)
    username = Column(String(200), nullable=False)
    display_name = Column(String(300))
    profile_url = Column(String(1000))
    bio = Column(Text)
    follower_count = Column(Integer, default=0)
    avatar_url = Column(String(1000))

    # Pipeline state
    status = Column(String(50), default="idle")
    # idle | discovering | scraping | processing | done | error
    pipeline_task_id = Column(String(200))
    error_message = Column(Text)
    last_pipeline_at = Column(DateTime)

    # Aggregated stats (refreshed after each pipeline run)
    total_posts_scraped = Column(Integer, default=0)
    total_comments = Column(Integer, default=0)
    positive_pct = Column(Float, default=0.0)
    negative_pct = Column(Float, default=0.0)
    neutral_pct = Column(Float, default=0.0)
    avg_sentiment_score = Column(Float, default=0.0)
    top_topics = Column(JSON, default=list)
    audience_mood = Column(String(50))

    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    platform = relationship("Platform")
    campaign = relationship("Campaign")
    posts = relationship("Post", back_populates="creator")
