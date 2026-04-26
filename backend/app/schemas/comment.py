from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class CommentOut(BaseModel):
    id: int
    post_id: int
    author: Optional[str]
    raw_text: str
    cleaned_text: Optional[str]
    arabized_text: Optional[str]
    language: Optional[str]
    sentiment: Optional[str]
    sentiment_score: Optional[float]
    sentiment_confidence: Optional[float]
    likes: int
    posted_at: Optional[datetime]
    analyzed_at: Optional[datetime]

    class Config:
        from_attributes = True
