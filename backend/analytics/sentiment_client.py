"""
Client for the Sentinelle AI sentiment engine.
The AI engine is a separate service connected via REST API.
When the engine is not reachable, falls back to a rule-based heuristic.
"""
import logging
from typing import List, Optional
import httpx
from app.config import settings

logger = logging.getLogger(__name__)

_TIMEOUT = 10.0


class SentimentResult:
    def __init__(self, label: str, score: float, confidence: float, emotions: dict):
        self.label = label          # positive / negative / neutral
        self.score = score          # -1.0 to 1.0
        self.confidence = confidence
        self.emotions = emotions    # {"joy": 0.8, "anger": 0.1, ...}


class SentimentClient:
    def __init__(self):
        self.base_url = settings.AI_ENGINE_URL
        self.api_key = settings.AI_ENGINE_API_KEY

    async def analyze(self, texts: List[str]) -> List[Optional[SentimentResult]]:
        """Send texts to the AI engine. Falls back to heuristic if unavailable."""
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.post(
                    f"{self.base_url}/analyze",
                    json={"texts": texts},
                    headers={"X-API-Key": self.api_key},
                )
                resp.raise_for_status()
                results = resp.json()["results"]
                return [
                    SentimentResult(
                        label=r["label"],
                        score=r["score"],
                        confidence=r["confidence"],
                        emotions=r.get("emotions", {}),
                    )
                    for r in results
                ]
        except Exception as e:
            logger.warning("AI engine unavailable (%s), using heuristic fallback", e)
            return [self._heuristic(t) for t in texts]

    def _heuristic(self, text: str) -> SentimentResult:
        """Simple keyword-based fallback for when AI engine is offline."""
        pos_words = {"برافو", "مزيان", "شكرا", "نحب", "جميل", "رائع", "ممتاز", "good", "great", "love", "👍", "❤️", "😍"}
        neg_words = {"قبيح", "ماعجبنيش", "خايب", "سيء", "horrible", "bad", "hate", "👎", "😡", "🤮"}
        lower = text.lower()
        pos = sum(1 for w in pos_words if w in lower)
        neg = sum(1 for w in neg_words if w in lower)
        if pos > neg:
            return SentimentResult("positive", 0.5, 0.4, {"joy": 0.6})
        elif neg > pos:
            return SentimentResult("negative", -0.5, 0.4, {"anger": 0.6})
        return SentimentResult("neutral", 0.0, 0.5, {})
