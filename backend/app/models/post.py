from sqlalchemy import Column, Integer, String, DateTime, Text, ForeignKey, BigInteger
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
from app.database import Base


class Post(Base):
    __tablename__ = "posts"

    id = Column(Integer, primary_key=True, index=True)
    platform_id = Column(Integer, ForeignKey("platforms.id"), nullable=False)
    campaign_id = Column(Integer, ForeignKey("campaigns.id"))
    creator_id = Column(Integer, ForeignKey("creators.id"), nullable=True)
    external_id = Column(String(500), unique=True, nullable=False)  # platform's post id
    url = Column(String(1000))
    author = Column(String(200))
    caption = Column(Text)
    likes = Column(BigInteger, default=0)
    views = Column(BigInteger, default=0)
    shares = Column(BigInteger, default=0)
    comment_count = Column(Integer, default=0)
    scraped_at = Column(DateTime, default=lambda: datetime.utcnow())
    posted_at = Column(DateTime)
    tags = Column(Text, default="[]")         # JSON array of hashtag strings
    media_type = Column(Integer, default=1)   # 1=Photo, 2=Video/Reel, 8=Carousel
    is_collab = Column(Integer, default=0)    # 1 if post has co-authors
    counts_disabled = Column(Integer, default=0)  # 1 if creator hid like/view counts
    thumbnail_url = Column(Text, default="")  # cover image URL (CDN, may expire)
    raw_data_path = Column(String(500))
    etl_status = Column(String(50), default="pending")  # pending, cleaned, transformed, analyzed

    platform = relationship("Platform", back_populates="posts")
    campaign = relationship("Campaign", back_populates="posts")
    creator = relationship("Creator", back_populates="posts")
    comments = relationship("Comment", back_populates="post")
