import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from app.config import settings
from app.database import init_db
from app.core.security import get_current_user, ensure_default_admin
from app.routers import (
    auth, campaigns, creators, analytics, reports, dashboard, matching, comments, pipeline, privacy
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    await ensure_default_admin()
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

# Public auth routes (login / me / register)
app.include_router(auth.router, prefix="/api/auth", tags=["auth"])

# All feature routers require a valid JWT (Authorization: Bearer <token>)
_secured = [Depends(get_current_user)]
app.include_router(campaigns.router,  prefix="/api/campaigns",  tags=["campaigns"], dependencies=_secured)
app.include_router(creators.router,   prefix="/api/creators",   tags=["creators"],  dependencies=_secured)
app.include_router(analytics.router,  prefix="/api/analytics",  tags=["analytics"], dependencies=_secured)
app.include_router(reports.router,    prefix="/api/reports",    tags=["reports"],   dependencies=_secured)
app.include_router(dashboard.router,  prefix="/api/dashboard",  tags=["dashboard"], dependencies=_secured)
app.include_router(matching.router,   prefix="/api/matching",   tags=["matching"],  dependencies=_secured)
app.include_router(comments.router,   prefix="/api/comments",   tags=["comments"],  dependencies=_secured)
app.include_router(pipeline.router,   prefix="/api/pipeline",   tags=["pipeline"],  dependencies=_secured)
app.include_router(privacy.router,    prefix="/api/privacy",    tags=["privacy"],   dependencies=_secured)

_THUMBS_DIR = "/app/data/thumbnails"
os.makedirs(_THUMBS_DIR, exist_ok=True)
app.mount("/api/thumbnails", StaticFiles(directory=_THUMBS_DIR), name="thumbnails")


@app.get("/api/health")
async def health():
    return {"status": "ok", "service": "Sentinelle API v2"}


@app.get("/api/proxy/image")
async def proxy_image(url: str):
    """Proxy social-media CDN images so the browser doesn't hit them directly."""
    import httpx
    from fastapi import Response, HTTPException
    from urllib.parse import unquote

    decoded = unquote(url)
    allowed = ("fbcdn.net", "cdninstagram.com", "ytimg.com", "ggpht.com", "youtube.com")
    if not any(h in decoded for h in allowed):
        raise HTTPException(400, "URL not from an allowed CDN")
    try:
        referer = "https://www.youtube.com/" if ("ytimg.com" in decoded or "youtube.com" in decoded) else "https://www.instagram.com/"
        headers = {
            "Referer": referer,
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
            "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get(decoded, headers=headers)
        if resp.status_code >= 400:
            raise HTTPException(resp.status_code, f"CDN returned {resp.status_code}")
        return Response(
            content=resp.content,
            media_type=resp.headers.get("content-type", "image/jpeg"),
            headers={"Cache-Control": "public, max-age=3600"},
        )
    except HTTPException:
        raise
    except Exception as exc:
        import logging as _log
        _log.getLogger(__name__).warning("proxy_image failed for %s: %s", decoded[:80], exc)
        raise HTTPException(502, "Failed to fetch image")


@app.get("/api/debug/ai")
async def debug_ai():
    """Test both Groq (generation) and BGE Space (embeddings) connectivity."""
    from groq import Groq
    results = {}

    # Groq
    groq_key = settings.GROQ_API_KEY
    if not groq_key:
        results["groq"] = {"ok": False, "error": "GROQ_API_KEY not set"}
    else:
        try:
            client = Groq(api_key=groq_key)
            resp = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "user", "content": "Reply with just the word: ok"}],
                max_tokens=5,
            )
            results["groq"] = {
                "ok": True,
                "model": "llama-3.3-70b-versatile",
                "response": resp.choices[0].message.content.strip(),
            }
        except Exception as exc:
            results["groq"] = {"ok": False, "error": str(exc)}

    # BGE Embeddings (BAAI/bge-m3 via HF Space)
    from analytics.embedding_service import EmbeddingService, _BGE_DIM
    svc = EmbeddingService()
    if not svc._bge_url:
        results["bge_embeddings"] = {"ok": False, "error": "BGE_SPACE_URL not set"}
    else:
        try:
            ready = svc._bge_ready()
            results["bge_embeddings"] = {
                "ok": ready,
                "model": "BAAI/bge-m3",
                "dimensions": _BGE_DIM,
                **({} if ready else {"error": "Space not ready (sleeping or unreachable)"}),
            }
        except Exception as exc:
            results["bge_embeddings"] = {"ok": False, "error": str(exc)}

    return results
