from sqlalchemy import Column, Integer, String, DateTime, Float, ForeignKey, JSON
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
from app.database import Base


class Metric(Base):
    __tablename__ = "metrics"

    id = Column(Integer, primary_key=True, index=True)
    campaign_id = Column(Integer, ForeignKey("campaigns.id"), nullable=False)
    period = Column(String(20), nullable=False)          # daily, weekly, monthly
    period_start = Column(DateTime, nullable=False)
    period_end = Column(DateTime, nullable=False)

    # Volume metrics
    total_comments = Column(Integer, default=0)
    total_posts = Column(Integer, default=0)

    # Sentiment breakdown
    positive_count = Column(Integer, default=0)
    negative_count = Column(Integer, default=0)
    neutral_count = Column(Integer, default=0)
    avg_sentiment_score = Column(Float, default=0.0)

    # Engagement
    impression_score = Column(Float, default=0.0)       # weighted reach estimate
    virality_score = Column(Float, default=0.0)         # shares / total interactions
    engagement_rate = Column(Float, default=0.0)        # (likes+comments+shares) / views

    # Audience mood
    audience_mood = Column(String(50))                  # happy, angry, neutral, mixed
    mood_shift = Column(Float, default=0.0)             # change vs previous period

    # Trending topics
    trending_topics = Column(JSON, default=list)        # [{"topic": str, "count": int}]
    top_keywords = Column(JSON, default=list)

    # Alert flags
    negative_spike = Column(Integer, default=0)         # 1 if negative > threshold

    computed_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    campaign = relationship("Campaign", back_populates="metrics")
