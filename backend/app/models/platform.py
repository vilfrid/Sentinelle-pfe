from sqlalchemy import Column, Integer, String, DateTime
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
from app.database import Base


class Platform(Base):
    __tablename__ = "platforms"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(50), unique=True, nullable=False)  # instagram, youtube
    display_name = Column(String(100))
    created_at = Column(DateTime, default=lambda: datetime.utcnow())

    posts = relationship("Post", back_populates="platform")
    influencers = relationship("Influencer", back_populates="platform")
