from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings
from app.database import init_db
from app.routers import (
    campaigns, creators, analytics, reports, dashboard, matching, comments
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(
    title="Sentinelle API",
    description="Community management platform with AI-powered sentiment analysis for Tunisian Arabizi",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(campaigns.router,  prefix="/api/campaigns",  tags=["campaigns"])
app.include_router(creators.router,   prefix="/api/creators",   tags=["creators"])
app.include_router(analytics.router,  prefix="/api/analytics",  tags=["analytics"])
app.include_router(reports.router,    prefix="/api/reports",    tags=["reports"])
app.include_router(dashboard.router,  prefix="/api/dashboard",  tags=["dashboard"])
app.include_router(matching.router,   prefix="/api/matching",   tags=["matching"])
app.include_router(comments.router,   prefix="/api/comments",   tags=["comments"])


@app.get("/api/health")
async def health():
    return {"status": "ok", "service": "Sentinelle API v2"}
