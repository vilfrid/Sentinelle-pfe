from pydantic_settings import BaseSettings
from typing import List


class Settings(BaseSettings):
    DATABASE_URL: str = "sqlite+aiosqlite:///./sentinelle.db"
    AI_ENGINE_URL: str = "http://localhost:8001"
    AI_ENGINE_API_KEY: str = ""
    GOOGLE_API_KEY: str = ""
    INSTAGRAM_SESSION_ID: str = ""
    TIKTOK_COOKIES: str = ""        # raw cookie string from browser DevTools
    SECRET_KEY: str = "change-me-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440
    REDIS_URL: str = "redis://localhost:6379/0"
    CORS_ORIGINS: str = "http://localhost:5173,http://localhost:3000"

    @property
    def cors_origins_list(self) -> List[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",")]

    class Config:
        env_file = ".env"


settings = Settings()
