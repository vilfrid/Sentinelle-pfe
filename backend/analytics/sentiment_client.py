"""
Client for the Sentinelle AI sentiment engine.
Batches run concurrently with asyncio.gather for faster throughput.
"""
import asyncio
import logging
from typing import List, Optional
import httpx
from app.config import settings

logger = logging.getLogger(__name__)

_BATCH_TIMEOUT = 180.0  # HF Spaces need ~2 min cold start — 60s was timing out every run
_BATCH_SIZE = 50
_RETRY_DELAY = 5        # seconds before retrying a failed batch
_MAX_CONCURRENT = 4     # max parallel batches to avoid overwhelming the AI server
_WARMUP_TIMEOUT = 200.0 # warmup ping waits longer — first request after sleep takes the most time


class SentimentResult:
    def __init__(self, label: str, score: float, confidence: float, emotions: dict):
        self.label = label
        self.score = score
        self.confidence = confidence
        self.emotions = emotions


class SentimentClient:
    def __init__(self):
        self.base_url = settings.AI_ENGINE_URL
        self.api_key = settings.AI_ENGINE_API_KEY

    async def _send_batch(
        self, client: httpx.AsyncClient, texts: List[str], batch_num: int, total_batches: int
    ) -> List[Optional[SentimentResult]]:
        for attempt in range(2):
            try:
                resp = await client.post(
                    f"{self.base_url}/analyze",
                    json={"texts": texts},
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    timeout=_BATCH_TIMEOUT,
                )
                resp.raise_for_status()
                results = resp.json()["results"]
                logger.info("Sentiment batch %d/%d: %d results received", batch_num, total_batches, len(results))
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

    async def warmup(self) -> bool:
        """
        Send a single dummy text to wake the HF Space before the real pipeline starts.
        HF Spaces sleep after ~15 min of inactivity and take ~2 min to cold-start.
        Calling this early means sentiment batches arrive to a warm instance.
        Returns True if the space responded, False if it timed out.
        """
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    f"{self.base_url}/analyze",
                    json={"texts": ["warmup"]},
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    timeout=_WARMUP_TIMEOUT,
                )
                resp.raise_for_status()
                logger.info("Sentiment engine warmup OK (%s)", self.base_url)
                return True
        except Exception as exc:
            logger.warning("Sentiment engine warmup failed (will retry during scraping): %s", exc)
            return False

    async def analyze(self, texts: List[str]) -> List[Optional[SentimentResult]]:
        """
        Split into batches of 50, run up to _MAX_CONCURRENT batches in parallel.
        Returns None per entry for any batch that fails after one retry.
        """
        batches = [texts[i:i + _BATCH_SIZE] for i in range(0, len(texts), _BATCH_SIZE)]
        total_batches = len(batches)
        logger.info(
            "Starting sentiment analysis: %d texts in %d batch(es) of up to %d (max %d concurrent)",
            len(texts), total_batches, _BATCH_SIZE, _MAX_CONCURRENT,
        )

        all_results: List[Optional[SentimentResult]] = [None] * len(texts)

        async with httpx.AsyncClient() as client:
            sem = asyncio.Semaphore(_MAX_CONCURRENT)

            async def bounded(idx: int, batch: List[str]):
                async with sem:
                    return idx, await self._send_batch(client, batch, idx + 1, total_batches)

            tasks = [bounded(i, batch) for i, batch in enumerate(batches)]
            for coro in asyncio.as_completed(tasks):
                idx, results = await coro
                start = idx * _BATCH_SIZE
                for j, r in enumerate(results):
                    all_results[start + j] = r

        analyzed = sum(1 for r in all_results if r is not None)
        logger.info("Sentiment analysis complete: %d/%d comments analyzed successfully", analyzed, len(texts))
        return all_results
