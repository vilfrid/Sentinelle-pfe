"""
Client for the Sentinelle AI sentiment engine.
The AI engine is a separate service connected via REST API.
"""
import asyncio
import logging
from typing import List, Optional
import httpx
from app.config import settings

logger = logging.getLogger(__name__)

_TIMEOUT = 300.0   # AI engine needs up to 5 min for large batches
_BATCH_SIZE = 50
_RETRY_DELAY = 5   # seconds before retrying a failed batch


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

    async def _send_batch(
        self, client: httpx.AsyncClient, texts: List[str], batch_num: int, total_batches: int
    ) -> List[Optional["SentimentResult"]]:
        """Send one batch with one retry on failure. Returns None per entry on permanent failure."""
        for attempt in range(2):
            try:
                resp = await client.post(
                    f"{self.base_url}/analyze",
                    json={"texts": texts},
                    headers={"Authorization": f"Bearer {self.api_key}"},
                )
                resp.raise_for_status()
                results = resp.json()["results"]
                logger.info(
                    "Sentiment batch %d/%d: %d results received",
                    batch_num, total_batches, len(results),
                )
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
                if attempt == 0:
                    logger.warning(
                        "Sentiment batch %d/%d failed (attempt 1), retrying in %ds: %s",
                        batch_num, total_batches, _RETRY_DELAY, e,
                    )
                    await asyncio.sleep(_RETRY_DELAY)
                else:
                    logger.error(
                        "Sentiment batch %d/%d failed after retry — %d comments left unanalyzed: %s",
                        batch_num, total_batches, len(texts), e,
                    )
                    return [None] * len(texts)

    async def analyze(self, texts: List[str]) -> List[Optional[SentimentResult]]:
        """
        Split texts into batches of 50, send each to the AI engine in order,
        and merge results back. Blocks until ALL batches are complete.
        Returns None for each entry in any batch that fails after one retry.
        """
        batches = [texts[i:i + _BATCH_SIZE] for i in range(0, len(texts), _BATCH_SIZE)]
        total_batches = len(batches)
        logger.info(
            "Starting sentiment analysis: %d texts in %d batch(es) of up to %d",
            len(texts), total_batches, _BATCH_SIZE,
        )

        all_results: List[Optional[SentimentResult]] = []
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            for idx, batch in enumerate(batches, start=1):
                batch_results = await self._send_batch(client, batch, idx, total_batches)
                all_results.extend(batch_results)

        analyzed = sum(1 for r in all_results if r is not None)
        logger.info(
            "Sentiment analysis complete: %d/%d comments analyzed successfully",
            analyzed, len(texts),
        )
        return all_results
