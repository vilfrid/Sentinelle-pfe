from pydantic_settings import BaseSettings
from typing import List


class Settings(BaseSettings):
    DATABASE_URL: str = "sqlite+aiosqlite:///./sentinelle.db"
    AI_ENGINE_URL: str = "http://localhost:8001"
    AI_ENGINE_API_KEY: str = ""
    GROQ_API_KEY: str = ""
    HF_SPACE_URL: str = ""          # e.g. https://YOUR_USERNAME-sentinelle-topics.hf.space
    BGE_SPACE_URL: str = ""         # e.g. https://YOUR_USERNAME-sentinelle-embedder.hf.space
    OLLAMA_URL: str = ""            # e.g. http://host.docker.internal:11434
    OLLAMA_MODEL: str = "qwen2.5:7b"
    INSTAGRAM_SESSION_ID: str = ""
    TIKTOK_COOKIES: str = ""        # raw cookie string from browser DevTools
    SECRET_KEY: str = "change-me-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440
    # Default admin seeded at first startup if the users table is empty
    ADMIN_EMAIL: str = "admin@medianet.tn"
    ADMIN_PASSWORD: str = "Sentinelle2026!"
    # GDPR / RGPD
    PSEUDONYM_SALT: str = "change-this-pseudonym-salt-in-production"
    COMMENT_RETENTION_DAYS: int = 365   # auto-purge comments older than this
    REDIS_URL: str = "redis://localhost:6379/0"
    CORS_ORIGINS: str = "http://localhost:5173,http://localhost:3000"

    @property
    def cors_origins_list(self) -> List[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",")]

    class Config:
        env_file = ".env"


settings = Settings()
