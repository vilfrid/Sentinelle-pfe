from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class PostOut(BaseModel):
    id: int
    external_id: str
    url: Optional[str]
    author: Optional[str]
    caption: Optional[str]
    likes: int
    views: int
    shares: int
    comment_count: int
    scraped_at: datetime
    etl_status: str

    class Config:
        from_attributes = True
