from sqlalchemy import Column, Integer, String, DateTime, Text, ForeignKey, Float, UniqueConstraint
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
from app.database import Base


class Comment(Base):
    __tablename__ = "comments"

    # --- ADDED THIS BLOCK ---
    # This forces the database to reject any duplicate comments for a given post
    __table_args__ = (
        UniqueConstraint('post_id', 'external_id', name='uq_post_comment_external_id'),
    )
    # ------------------------

    id = Column(Integer, primary_key=True, index=True)
    post_id = Column(Integer, ForeignKey("posts.id"), nullable=False)
    external_id = Column(String(500))
    author = Column(String(200))

    # Text pipeline stages
    raw_text = Column(Text, nullable=False)            # original scraped text
    cleaned_text = Column(Text)                        # after cleaning
    language = Column(String(20))                      # ar, fr, en, arabizi, mixed (multilingual model handles all)

    # Sentiment (populated by AI engine)
    sentiment = Column(String(20))                     # positive, negative, neutral
    sentiment_score = Column(Float)                    # -1.0 to 1.0
    sentiment_confidence = Column(Float)               # 0.0 to 1.0
    emotions = Column(String(200))                     # JSON: joy, anger, fear, etc.

    likes = Column(Integer, default=0)
    posted_at = Column(DateTime)
    scraped_at = Column(DateTime, default=lambda: datetime.utcnow())
    analyzed_at = Column(DateTime)

    post = relationship("Post", back_populates="comments")