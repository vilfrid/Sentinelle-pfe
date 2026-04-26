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
import logging
from datetime import datetime, timezone
from pathlib import Path

from celery import chain, group, chord
from workers.celery_app import celery_app
from app.database import get_sync_db
from app.config import settings

logger = logging.getLogger(__name__)


# ── helpers ───────────────────────────────────────────────────────────────────

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


# ── Task 1: discover all posts for a creator ──────────────────────────────────

@celery_app.task(bind=True, name="workers.tasks.launch_creator_pipeline")
def launch_creator_pipeline(self, creator_id: int):
    """Entry point: discovers posts then fans out one task per post."""
    info = _get_creator(creator_id)
    if not info:
        return {"error": "creator not found"}

    _set_creator_status(creator_id, "discovering")
    logger.info("Discovering posts for creator %s (%s)", info["username"], info["platform"])

    try:
        identifier = info["profile_url"] or info["username"]
        kwargs = {}
        if info["platform"] == "instagram":
            kwargs["session_id"] = settings.INSTAGRAM_SESSION_ID

        posts = asyncio.run(
            __import__("scraping.profile_scraper", fromlist=["discover_posts"])
            .discover_posts(info["platform"], identifier, **kwargs)
        )
    except Exception as exc:
        _set_creator_status(creator_id, "error", str(exc))
        logger.exception("Discovery failed for creator %d", creator_id)
        raise self.retry(exc=exc)

    if not posts:
        _set_creator_status(creator_id, "done")
        return {"discovered": 0}

    _set_creator_status(creator_id, "scraping")

    # Fan out: one task per post, then finalize
    post_tasks = group(
        scrape_and_process_post.s(p["url"], p["external_id"], info["platform"], creator_id)
        for p in posts
    )
    workflow = chord(post_tasks)(finalize_creator.s(creator_id))
    workflow.apply_async()

    logger.info("Launched %d post tasks for creator %d", len(posts), creator_id)
    return {"discovered": len(posts)}


# ── Task 2: scrape one post + run ETL + sentiment ─────────────────────────────

@celery_app.task(bind=True, name="workers.tasks.scrape_and_process_post")
def scrape_and_process_post(self, url: str, external_id: str, platform: str, creator_id: int):
    """Scrape a single post URL then run ETL + sentiment inline."""
    from app.models.post import Post
    from app.models.platform import Platform
    from app.models.creator import Creator

    db = get_sync_db()
    try:
        # Resolve platform_id
        platform_obj = db.query(Platform).filter(Platform.name == platform).first()
        if not platform_obj:
            platform_obj = Platform(name=platform, display_name=platform.capitalize())
            db.add(platform_obj)
            db.commit()
            db.refresh(platform_obj)

        creator = db.get(Creator, creator_id)
        campaign_id = creator.campaign_id if creator else None

        # Skip if already scraped
        existing = db.query(Post).filter(Post.external_id == external_id).first()
        if existing:
            return {"post_id": existing.id, "skipped": True}

        # Create post record
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

    # Scrape
    try:
        scraper_map = {
            "instagram": "scraping.instagram.InstagramScraper",
            "tiktok": "scraping.tiktok.TikTokScraper",
            "youtube": "scraping.youtube.YouTubeScraper",
            "facebook": "scraping.facebook.FacebookScraper",
        }
        module_path, cls_name = scraper_map[platform].rsplit(".", 1)
        mod = __import__(module_path, fromlist=[cls_name])
        scraper = getattr(mod, cls_name)()
        jsonl_path = asyncio.run(scraper.scrape(url))
    except Exception as exc:
        logger.exception("Scrape failed for %s", url)
        _update_post_status(post_id, "scrape_failed")
        return {"post_id": post_id, "error": str(exc)}

    # Store raw data path
    _update_post_status(post_id, "scraped", raw_data_path=str(jsonl_path))

    # ETL
    try:
        from etl.cleaners import CLEANERS
        from etl.transformers.arabizi_transformer import ArabiziTransformer
        from app.models.comment import Comment

        cleaner = CLEANERS[platform]()
        raw_comments = cleaner.extract_comments(jsonl_path)
        transformer = ArabiziTransformer()
        texts = [c["raw_text"] for c in raw_comments]
        arabized = transformer.transform_batch(texts)

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
        finally:
            db.close()

        _update_post_status(post_id, "transformed")
    except Exception as exc:
        logger.exception("ETL failed for post %d", post_id)
        _update_post_status(post_id, "etl_failed")
        return {"post_id": post_id, "error": str(exc)}

    # Sentiment
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

        _update_post_status(post_id, "analyzed")
    except Exception as exc:
        logger.exception("Sentiment failed for post %d", post_id)

    return {"post_id": post_id, "done": True}


# ── Task 3: aggregate stats back onto the Creator ─────────────────────────────

@celery_app.task(name="workers.tasks.finalize_creator")
def finalize_creator(results, creator_id: int):
    """Called after all posts are processed. Aggregates stats onto Creator."""
    from app.models.creator import Creator
    from app.models.post import Post
    from app.models.comment import Comment
    from analytics.topics_engine import extract_trending_topics

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
        neutral = total - positive - negative
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

        logger.info("Creator %d finalized: %d posts, %d comments, mood=%s", creator_id, len(posts), total, mood)
    finally:
        db.close()


# ── helper ────────────────────────────────────────────────────────────────────

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
