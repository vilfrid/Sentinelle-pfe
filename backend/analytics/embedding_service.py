"""
Embedding service — uses BAAI/bge-m3 via the BGE HF Space (BGE_SPACE_URL).
No fallback: if the Space is not ready, embeddings are skipped and the caller
gets None values (matching falls back to keyword Jaccard instead of cosine).
"""
import logging
import time
from typing import List, Optional

logger = logging.getLogger(__name__)

_BGE_DIM           = 1024   # BAAI/bge-m3 dense dimension
_BGE_WARMUP_WAIT   = 90     # seconds to poll /health on cold start / wake from sleep
_BGE_EMBED_TIMEOUT = 120    # seconds per batch HTTP request
_BGE_BATCH_SIZE    = 32     # texts per request to the Space


class EmbeddingService:
    def __init__(self):
        from app.config import settings
        self._bge_url = getattr(settings, "BGE_SPACE_URL", "").strip().rstrip("/")
        token = getattr(settings, "AI_ENGINE_API_KEY", "").strip()
        self._headers = {"Authorization": f"Bearer {token}"} if token else {}

    # ── Public API ────────────────────────────────────────────────────────────

    def generate_embedding(self, text: str) -> Optional[List[float]]:
        results = self.generate_embeddings_batch([text])
        return results[0] if results else None

    def generate_embeddings_batch(self, texts: List[str]) -> List[Optional[List[float]]]:
        """Embed multiple texts in one round-trip. Returns None per slot on failure."""
        if not texts:
            return []
        if not self._bge_url:
            logger.error("BGE_SPACE_URL not configured — cannot generate embeddings")
            return [None] * len(texts)

        result = self._bge_batch(texts)
        if result is None:
            logger.error("BGE Space unavailable — embeddings skipped (matching will use keyword fallback)")
            return [None] * len(texts)
        return result

    def embedding_dim(self) -> int:
        return _BGE_DIM

    # ── BGE Space ─────────────────────────────────────────────────────────────

    def _bge_ready(self) -> bool:
        import httpx
        url = f"{self._bge_url}/health"
        try:
            r = httpx.get(url, headers=self._headers, timeout=20, follow_redirects=True)
            body = r.text.strip()
            if not body:
                logger.warning("BGE /health HTTP %s empty body", r.status_code)
                return False
            if not body.startswith("{"):
                logger.warning("BGE /health non-JSON (auth/proxy page?): %s", body[:120])
                return False
            data = r.json()
            status = data.get("status")
            if r.status_code == 200 and status == "ready":
                return True
            logger.warning("BGE /health HTTP %s status=%r", r.status_code, status)
            return False
        except Exception as exc:
            logger.warning("BGE /health error: %s: %s", type(exc).__name__, exc)
            return False

    def _bge_warmup(self) -> bool:
        """Poll /health until Space wakes from sleep or timeout."""
        logger.info("BGE Space not ready — polling for up to %ds …", _BGE_WARMUP_WAIT)
        deadline = time.time() + _BGE_WARMUP_WAIT
        attempt = 0
        while time.time() < deadline:
            attempt += 1
            if self._bge_ready():
                logger.info("BGE Space ready after %d probe(s)", attempt)
                return True
            time.sleep(5)
        logger.warning("BGE Space did not respond within %ds (%d probes)", _BGE_WARMUP_WAIT, attempt)
        return False

    def _bge_batch(self, texts: List[str]) -> Optional[List[Optional[List[float]]]]:
        import httpx

        if not self._bge_ready():
            if not self._bge_warmup():
                return None

        results: List[Optional[List[float]]] = [None] * len(texts)
        any_success = False

        for start in range(0, len(texts), _BGE_BATCH_SIZE):
            chunk = texts[start: start + _BGE_BATCH_SIZE]
            try:
                resp = httpx.post(
                    f"{self._bge_url}/embed",
                    json={"texts": chunk, "batch_size": _BGE_BATCH_SIZE},
                    headers=self._headers,
                    timeout=_BGE_EMBED_TIMEOUT,
                )
                resp.raise_for_status()
                data = resp.json()
                embeddings = data.get("embeddings", [])
                if len(embeddings) == len(chunk):
                    for i, emb in enumerate(embeddings):
                        results[start + i] = emb
                    any_success = True
                    logger.info("BGE batch %d-%d OK (%s-dim)", start, start + len(chunk) - 1, data.get("dim", "?"))
                else:
                    logger.warning("BGE batch size mismatch: got %d for %d texts", len(embeddings), len(chunk))
            except Exception as exc:
                logger.warning("BGE batch %d-%d failed: %s", start, start + len(chunk), exc)

        return results if any_success else None

    # ── Text builders ─────────────────────────────────────────────────────────

    def build_creator_text(
        self,
        username: str,
        bio: Optional[str],
        topics: List[str],
        mood: Optional[str],
        hashtags: List[str] = None,
        platform: str = None,
        follower_count: int = 0,
        avg_views: float = 0.0,
        avg_shares: float = 0.0,
        engagement_rate: float = 0.0,
    ) -> str:
        parts = [f"Social media creator @{username}"]
        if platform:
            parts.append(f"Platform: {platform}")
        if bio:
            parts.append(f"Bio: {bio}")
        if topics:
            parts.append(f"Main content themes: {', '.join(topics)}")
        if hashtags:
            parts.append(f"Frequently used hashtags: {', '.join(hashtags)}")
        if mood:
            parts.append(f"Audience sentiment profile: {mood}")
        if follower_count >= 1_000_000:
            parts.append(f"Mega influencer with {follower_count // 1_000_000}M+ followers")
        elif follower_count >= 100_000:
            parts.append(f"Macro influencer with {follower_count // 1_000}K followers")
        elif follower_count >= 10_000:
            parts.append(f"Micro influencer with {follower_count // 1_000}K followers")
        elif follower_count > 0:
            parts.append(f"Nano influencer with {follower_count} followers")
        if avg_views >= 1_000_000:
            parts.append(f"Average {avg_views / 1_000_000:.1f}M views per post")
        elif avg_views >= 1_000:
            parts.append(f"Average {int(avg_views / 1_000)}K views per post")
        if avg_shares >= 10_000:
            parts.append(f"Average {avg_shares / 1_000:.0f}K reposts per post — highly shareable content")
        elif avg_shares >= 1_000:
            parts.append(f"Average {avg_shares / 1_000:.1f}K reposts per post")
        elif avg_shares >= 100:
            parts.append(f"Average {int(avg_shares)} reposts per post")
        if engagement_rate > 0:
            parts.append(f"Content engagement rate: {engagement_rate:.1f}%")
        return ". ".join(parts)

    def build_campaign_text(
        self,
        name: str,
        brand: str,
        description: Optional[str],
        keywords: List[str],
    ) -> str:
        parts = [f"Brand influencer campaign: {name} by {brand}"]
        if description:
            parts.append(f"Campaign description: {description}")
        if keywords:
            parts.append(f"Target keywords and content themes: {', '.join(keywords)}")
            parts.append(f"Looking for creators who talk about: {', '.join(keywords)}")
        return ". ".join(parts)
