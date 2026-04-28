"""
Full automated pipeline:

  launch_creator_pipeline(creator_id)
      ↓ (discover all post URLs)
  scrape_and_process_post(url, platform, creator_id)   ← one task per post
      ↓  scrape → JSONL
      ↓  ETL clean → arabize
      ↓  sentiment analysis
  finalize_creator(creator_id)
      ↓  compute aggregate stats (mood, pct, topics)
"""
import asyncio
import json
import logging
import random
import time
from datetime import datetime, timezone

import redis as redis_lib

from celery import group, chord
from workers.celery_app import celery_app
from app.database import get_sync_db
from app.config import settings

logger = logging.getLogger(__name__)

# ── Redis log buffer ──────────────────────────────────────────────────────────

_redis = redis_lib.from_url(settings.REDIS_URL, decode_responses=True)
_LOG_KEY = "pipeline:logs:{}"
_LOG_MAX = 200


def _log(creator_id: int, step: str, status: str, msg: str):
    """Push a log entry to Redis. status: info | ok | warn | error"""
    entry = json.dumps({
        "ts": datetime.now(timezone.utc).isoformat(),
        "step": step,
        "status": status,
        "msg": msg,
    })
    key = _LOG_KEY.format(creator_id)
    _redis.lpush(key, entry)
    _redis.ltrim(key, 0, _LOG_MAX - 1)
    _redis.expire(key, 86400)  # 24h TTL


def clear_logs(creator_id: int):
    _redis.delete(_LOG_KEY.format(creator_id))


# ── Stop flag ─────────────────────────────────────────────────────────────────

_STOP_KEY = "pipeline:stop:{}"


def set_stop_flag(creator_id: int):
    _redis.setex(_STOP_KEY.format(creator_id), 3600, "1")


def clear_stop_flag(creator_id: int):
    _redis.delete(_STOP_KEY.format(creator_id))


def _is_stopped(creator_id: int) -> bool:
    return _redis.exists(_STOP_KEY.format(creator_id)) > 0


# ── DB helpers ────────────────────────────────────────────────────────────────

def _set_creator_status(creator_id: int, status: str, error: str = None):
    db = get_sync_db()
    try:
        from app.models.creator import Creator
        creator = db.get(Creator, creator_id)
        if creator:
            creator.status = status
            if error:
                creator.error_message = error
            db.commit()
    finally:
        db.close()


def _get_creator(creator_id: int):
    db = get_sync_db()
    try:
        from app.models.creator import Creator
        from app.models.platform import Platform
        creator = db.get(Creator, creator_id)
        if not creator:
            return None
        platform = db.get(Platform, creator.platform_id)
        return {
            "id": creator.id,
            "username": creator.username,
            "profile_url": creator.profile_url,
            "platform": platform.name if platform else "unknown",
            "campaign_id": creator.campaign_id,
        }
    finally:
        db.close()


def _update_post_status(post_id: int, status: str, raw_data_path: str = None):
    db = get_sync_db()
    try:
        from app.models.post import Post
        post = db.get(Post, post_id)
        if post:
            post.etl_status = status
            if raw_data_path:
                post.raw_data_path = raw_data_path
            db.commit()
    finally:
        db.close()


# ── Task 1: discover all posts for a creator ──────────────────────────────────

@celery_app.task(bind=True, name="workers.tasks.launch_creator_pipeline")
def launch_creator_pipeline(self, creator_id: int):
    clear_logs(creator_id)
    clear_stop_flag(creator_id)
    _log(creator_id, "init", "info", "Pipeline started")

    info = _get_creator(creator_id)
    if not info:
        _log(creator_id, "init", "error", "Creator not found in DB")
        return {"error": "creator not found"}

    _log(creator_id, "init", "info", f"Creator: @{info['username']} | platform: {info['platform']}")
    _log(creator_id, "init", "info", f"Profile URL: {info['profile_url'] or '(none — using username)'}")

    if info["platform"] == "instagram":
        has_session = bool(settings.INSTAGRAM_SESSION_ID)
        _log(creator_id, "discover", "info" if has_session else "warn",
             f"INSTAGRAM_SESSION_ID: {'present' if has_session else 'MISSING — will scrape as guest (likely 0 posts)'}")

    if info["platform"] == "youtube":
        _log(creator_id, "discover", "info", "YouTube: no auth needed")

    if info["platform"] == "tiktok":
        _log(creator_id, "discover", "info", "TikTok: using persistent browser session")

    _set_creator_status(creator_id, "discovering")
    _log(creator_id, "discover", "info", "Launching browser to discover posts...")

    try:
        identifier = info["profile_url"] or info["username"]
        kwargs = {}
        if info["platform"] == "instagram":
            kwargs["session_id"] = settings.INSTAGRAM_SESSION_ID

        result = asyncio.run(
            __import__("scraping.profile_scraper", fromlist=["discover_posts"])
            .discover_posts(info["platform"], identifier, **kwargs)
        )
        posts = result if isinstance(result, list) else result.get("posts", [])
        page_title = result.get("page_title", "") if isinstance(result, dict) else ""
        if page_title:
            _log(creator_id, "discover", "info", f"Browser saw page: \"{page_title}\"")
        _log(creator_id, "discover", "ok" if posts else "warn",
             f"Discovery complete: found {len(posts)} post(s)")

    except Exception as exc:
        _log(creator_id, "discover", "error", f"Discovery crashed: {exc}")
        _set_creator_status(creator_id, "error", str(exc))
        logger.exception("Discovery failed for creator %d", creator_id)
        raise self.retry(exc=exc)

    if not posts:
        _log(creator_id, "discover", "warn",
             "0 posts found. Possible causes: session expired, private account, bot detection, or wrong URL")
        _set_creator_status(creator_id, "done")
        return {"discovered": 0}

    _set_creator_status(creator_id, "scraping")
    _log(creator_id, "scrape", "info", f"Fanning out {len(posts)} post tasks in parallel...")

    post_tasks = group(
        scrape_and_process_post.s(p["url"], p["external_id"], info["platform"], creator_id)
        for p in posts
    )
    chord(post_tasks)(finalize_creator.s(creator_id))

    return {"discovered": len(posts)}


# ── Task 2: scrape one post + ETL + sentiment ─────────────────────────────────

@celery_app.task(bind=True, name="workers.tasks.scrape_and_process_post")
def scrape_and_process_post(self, url: str, external_id: str, platform: str, creator_id: int):
    if _is_stopped(creator_id):
        return {"skipped": True, "reason": "stopped"}

    # Stagger parallel Instagram requests so the same session isn't hit simultaneously.
    # Without this, Instagram rate-limits and returns next_max_id=null after page 1.
    if platform == "instagram":
        time.sleep(random.uniform(1, 10))

    from app.models.post import Post
    from app.models.platform import Platform
    from app.models.creator import Creator

    short_url = url.split("?")[0][-60:]

    # ── DB setup ──
    db = get_sync_db()
    try:
        platform_obj = db.query(Platform).filter(Platform.name == platform).first()
        if not platform_obj:
            platform_obj = Platform(name=platform, display_name=platform.capitalize())
            db.add(platform_obj)
            db.commit()
            db.refresh(platform_obj)

        creator = db.get(Creator, creator_id)
        campaign_id = creator.campaign_id if creator else None

        existing = db.query(Post).filter(Post.external_id == external_id).first()
        if existing:
            if existing.etl_status in ("transformed", "analyzed"):
                _log(creator_id, "scrape", "info", f"Skipped (already processed): {short_url}")
                return {"post_id": existing.id, "skipped": True}
            # exists but not yet processed (e.g. stale pending from a cancelled run) — re-process it
            _log(creator_id, "scrape", "info", f"Re-processing unfinished post: {short_url}")
            post_id = existing.id
            existing.etl_status = "pending"
            db.commit()
        else:
            post = Post(
                platform_id=platform_obj.id,
                campaign_id=campaign_id,
                creator_id=creator_id,
                external_id=external_id,
                url=url,
                etl_status="pending",
            )
            db.add(post)
            db.commit()
            db.refresh(post)
            post_id = post.id
    finally:
        db.close()

    # ── Scrape ──
    _log(creator_id, "scrape", "info", f"Scraping: {short_url}")
    try:
        scraper_map = {
            "instagram": "scraping.instagram.InstagramScraper",
            "tiktok":    "scraping.tiktok.TikTokScraper",
            "youtube":   "scraping.youtube.YouTubeScraper",
        }
        module_path, cls_name = scraper_map[platform].rsplit(".", 1)
        mod = __import__(module_path, fromlist=[cls_name])
        scraper = getattr(mod, cls_name)()
        jsonl_path = asyncio.run(scraper.scrape(url))
        _log(creator_id, "scrape", "ok", f"Scraped → {jsonl_path}")
    except Exception as exc:
        _log(creator_id, "scrape", "error", f"Scraper crashed on {short_url}: {exc}")
        _update_post_status(post_id, "scrape_failed")
        return {"post_id": post_id, "error": str(exc)}

    _update_post_status(post_id, "scraped", raw_data_path=str(jsonl_path))

    if not jsonl_path.exists() or jsonl_path.stat().st_size == 0:
        _log(creator_id, "etl", "warn",
             f"0 comments captured for {short_url} — JSONL empty (bot detection, no comments, or session issue)")
        _update_post_status(post_id, "etl_failed")
        return {"post_id": post_id, "comments": 0}

    # ── ETL clean ──
    _log(creator_id, "etl", "info", f"Running ETL cleaner ({platform})...")
    try:
        from etl.cleaners import CLEANERS
        cleaner = CLEANERS[platform]()
        raw_comments = cleaner.extract_comments(jsonl_path)
        _log(creator_id, "etl", "ok" if raw_comments else "warn",
             f"Cleaner extracted {len(raw_comments)} comment(s)" +
             (" — JSONL may be empty or format mismatch" if not raw_comments else ""))
    except Exception as exc:
        _log(creator_id, "etl", "error", f"Cleaner crashed: {exc}")
        _update_post_status(post_id, "etl_failed")
        return {"post_id": post_id, "error": str(exc)}

    if not raw_comments:
        _update_post_status(post_id, "etl_failed")
        return {"post_id": post_id, "error": "0 comments extracted"}

    # ── Arabizi transform ──
    _log(creator_id, "arabizi", "info",
         f"Sending {len(raw_comments)} texts to Gemma 3 27B (GOOGLE_API_KEY: "
         f"{'present' if settings.GOOGLE_API_KEY else 'MISSING'})...")
    try:
        from etl.transformers.arabizi_transformer import ArabiziTransformer
        transformer = ArabiziTransformer()
        texts = [c["raw_text"] for c in raw_comments]
        arabized = transformer.transform_batch(texts)
        ignored = sum(1 for a in arabized if transformer.is_ignored(a))
        _log(creator_id, "arabizi", "ok",
             f"Transformed {len(arabized)} texts — {ignored} ignored (pure foreign), "
             f"{len(arabized) - ignored} kept as Arabic")
    except Exception as exc:
        _log(creator_id, "arabizi", "error", f"Arabizi transformer crashed: {exc}")
        arabized = [""] * len(raw_comments)

    # ── Store comments ──
    _log(creator_id, "etl", "info", "Saving comments to DB...")
    try:
        from app.models.comment import Comment
        db = get_sync_db()
        try:
            stored = 0
            for raw, arab in zip(raw_comments, arabized):
                if db.query(Comment).filter(
                    Comment.post_id == post_id,
                    Comment.external_id == raw.get("external_id", ""),
                ).first():
                    continue
                c = Comment(
                    post_id=post_id,
                    external_id=raw.get("external_id", ""),
                    author=raw.get("author", ""),
                    raw_text=raw["raw_text"],
                    cleaned_text=raw["raw_text"],
                    arabized_text=arab if arab and not transformer.is_ignored(arab) else None,
                    language="arabizi" if arab and not transformer.is_ignored(arab) else "foreign",
                    likes=raw.get("likes", 0),
                )
                db.add(c)
                stored += 1
            db.commit()
            _log(creator_id, "etl", "ok", f"Stored {stored} new comment(s) in DB")
        finally:
            db.close()
        _update_post_status(post_id, "transformed")
    except Exception as exc:
        _log(creator_id, "etl", "error", f"DB store failed: {exc}")
        _update_post_status(post_id, "etl_failed")
        return {"post_id": post_id, "error": str(exc)}

    # ── Sentiment ──
    _log(creator_id, "sentiment", "info",
         f"Sending to AI engine ({settings.AI_ENGINE_URL}) in batches of 50...")
    try:
        from app.models.comment import Comment
        from analytics.sentiment_client import SentimentClient

        db = get_sync_db()
        try:
            comments = db.query(Comment).filter(
                Comment.post_id == post_id,
                Comment.sentiment == None,
            ).all()
            texts_to_analyze = [c.arabized_text or c.cleaned_text or c.raw_text for c in comments]
        finally:
            db.close()

        if texts_to_analyze:
            client = SentimentClient()
            results = asyncio.run(client.analyze(texts_to_analyze))

            db = get_sync_db()
            try:
                for comment, result in zip(comments, results):
                    if result:
                        comment.sentiment = result.label
                        comment.sentiment_score = result.score
                        comment.sentiment_confidence = result.confidence
                        comment.analyzed_at = datetime.now(timezone.utc)
                        db.add(comment)
                db.commit()
            finally:
                db.close()

            pos = sum(1 for r in results if r and r.label == "positive")
            neg = sum(1 for r in results if r and r.label == "negative")
            _log(creator_id, "sentiment", "ok",
                 f"Analyzed {len(results)} comments — {pos} positive, {neg} negative, "
                 f"{len(results)-pos-neg} neutral")
        else:
            _log(creator_id, "sentiment", "warn", "No comments to analyze for sentiment")

        _update_post_status(post_id, "analyzed")
    except Exception as exc:
        _log(creator_id, "sentiment", "error", f"Sentiment analysis crashed: {exc}")

    return {"post_id": post_id, "done": True}


# ── Task 3: finalize ──────────────────────────────────────────────────────────

@celery_app.task(name="workers.tasks.finalize_creator")
def finalize_creator(results, creator_id: int):
    from app.models.creator import Creator
    from app.models.post import Post
    from app.models.comment import Comment
    from analytics.topics_engine import extract_trending_topics

    _log(creator_id, "finalize", "info", "All posts processed — aggregating stats...")

    db = get_sync_db()
    try:
        creator = db.get(Creator, creator_id)
        if not creator:
            return

        posts = db.query(Post).filter(Post.creator_id == creator_id).all()
        post_ids = [p.id for p in posts]
        comments = db.query(Comment).filter(Comment.post_id.in_(post_ids)).all() if post_ids else []

        total = len(comments)
        positive = sum(1 for c in comments if c.sentiment == "positive")
        negative = sum(1 for c in comments if c.sentiment == "negative")
        neutral  = total - positive - negative
        avg_score = (
            sum(c.sentiment_score for c in comments if c.sentiment_score is not None) / total
            if total > 0 else 0.0
        )

        texts = [c.arabized_text or c.raw_text for c in comments if c.arabized_text or c.raw_text]
        top_topics = extract_trending_topics(texts, top_n=10)

        if total == 0:
            mood = "unknown"
        elif positive / total > 0.6:
            mood = "happy"
        elif negative / total > 0.4:
            mood = "angry"
        else:
            mood = "mixed"

        creator.total_posts_scraped = len(posts)
        creator.total_comments = total
        creator.positive_pct = round(positive / max(total, 1) * 100, 1)
        creator.negative_pct = round(negative / max(total, 1) * 100, 1)
        creator.neutral_pct = round(neutral / max(total, 1) * 100, 1)
        creator.avg_sentiment_score = round(avg_score, 4)
        creator.top_topics = top_topics
        creator.audience_mood = mood
        creator.status = "done"
        creator.last_pipeline_at = datetime.now(timezone.utc)
        db.commit()

        _log(creator_id, "finalize", "ok",
             f"Done — {len(posts)} posts, {total} comments, mood: {mood} "
             f"({positive} pos / {negative} neg / {neutral} neutral)")
    finally:
        db.close()
