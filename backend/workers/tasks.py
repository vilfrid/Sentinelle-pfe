"""
Full automated pipeline:

  launch_creator_pipeline(creator_id)
      ↓ (discover all post URLs)
  scrape_and_process_post(url, platform, creator_id)   ← one task per post
      ↓  scrape → JSONL
      ↓  ETL clean
      ↓  sentiment analysis
  finalize_creator(creator_id)
      ↓  compute aggregate stats (mood, pct, topics)
      ↓  generate embedding for matching
"""
import asyncio
import json
import logging
import random
import time
from datetime import datetime, timezone

import redis as redis_lib

from celery import group
from workers.celery_app import celery_app
from app.database import get_sync_db
from app.config import settings
from app.core.privacy import pseudonymize

logger = logging.getLogger(__name__)

# ── Redis log buffer ──────────────────────────────────────────────────────────

_redis = redis_lib.from_url(settings.REDIS_URL, decode_responses=True)
_LOG_KEY = "pipeline:logs:{}"
_LOG_MAX = 200


def _log(creator_id: int, step: str, status: str, msg: str):
    """Push a log entry to Redis.
    status: info | ok | warn | error"""
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


# ── Thumbnail downloader ──────────────────────────────────────────────────────

def _save_thumbnail(thumbnail_url: str, platform: str, external_id: str) -> str:
    """Download a CDN thumbnail and return its local /api/thumbnails/ path.
    Returns the original URL unchanged on failure or for YouTube (public CDN)."""
    if not thumbnail_url or not thumbnail_url.startswith("http"):
        return thumbnail_url
    if platform == "youtube" or "ytimg.com" in thumbnail_url or "youtube.com" in thumbnail_url:
        return thumbnail_url  # YouTube is public, no need to cache locally

    import os, httpx
    thumbs_dir = "/app/data/thumbnails"
    os.makedirs(thumbs_dir, exist_ok=True)

    ext = "webp" if ".webp" in thumbnail_url else "jpg"
    filename = f"{platform}_{external_id}.{ext}"
    local_path = os.path.join(thumbs_dir, filename)

    if os.path.exists(local_path):
        return f"/api/thumbnails/{filename}"

    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
            "Referer": "https://www.instagram.com/",
            "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
        }
        cookies = {}
        session_id = getattr(settings, "INSTAGRAM_SESSION_ID", "").strip()
        if session_id and ("fbcdn" in thumbnail_url or "cdninstagram" in thumbnail_url):
            cookies["sessionid"] = session_id

        resp = httpx.get(thumbnail_url, headers=headers, cookies=cookies,
                         timeout=15, follow_redirects=True)
        if resp.status_code == 200 and resp.content:
            with open(local_path, "wb") as f:
                f.write(resp.content)
            return f"/api/thumbnails/{filename}"
    except Exception as exc:
        logger.warning("Thumbnail download failed for %s: %s", external_id, exc)

    return thumbnail_url


# ── Stop flag ─────────────────────────────────────────────────────────────────

_STOP_KEY    = "pipeline:stop:{}"
_COUNTER_KEY = "pipeline:pending:{}"


def _init_counter(creator_id: int, n: int):
    _redis.setex(_COUNTER_KEY.format(creator_id), 7200, str(n))


def _decr_counter(creator_id: int) -> int:
    """Decrement task counter atomically. Returns remaining count (0 = all done)."""
    remaining = _redis.decr(_COUNTER_KEY.format(creator_id))
    return max(int(remaining), 0)


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
        creator_info = result.get("creator_info", {}) if isinstance(result, dict) else {}
        if page_title:
            _log(creator_id, "discover", "info", f"Browser saw page: \"{page_title}\"")
        _log(creator_id, "discover", "ok" if posts else "warn",
             f"Discovery complete: found {len(posts)} post(s)")

        # Update Creator with profile data discovered during scraping
        if creator_info:
            from app.models.creator import Creator as CreatorModel
            db = get_sync_db()
            try:
                creator_obj = db.get(CreatorModel, creator_id)
                if creator_obj:
                    fc = creator_info.get("follower_count")
                    if fc:
                        try:
                            creator_obj.follower_count = int(fc)
                        except (TypeError, ValueError):
                            pass
                    bio = creator_info.get("bio", "").strip()
                    if bio:
                        creator_obj.bio = bio
                    dn = creator_info.get("display_name", "").strip()
                    if dn:
                        creator_obj.display_name = dn
                    # Save avatar_url from any non-empty URL
                    # (Instagram CDN URLs expire — cache the file locally like post thumbnails)
                    av = (creator_info.get("avatar_url") or "").strip()
                    if av and av.startswith("http"):
                        creator_obj.avatar_url = _save_thumbnail(av, "instagram", f"avatar_{creator_id}")
                    db.commit()
                    _log(creator_id, "discover", "ok",
                         f"Profile synced: {creator_info.get('follower_count', '?')} followers, avatar={bool(av)}")
            except Exception as exc:
                db.rollback()
                _log(creator_id, "discover", "warn", f"Profile sync failed (non-fatal): {exc}")
            finally:
                db.close()

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

    # Wake the HF Space sentiment engine before fanning out posts.
    # Spaces sleep after ~15 min idle and take ~2 min to cold-start.
    # Without this, the first sentiment batches timeout and come back all-neutral.
    try:
        from analytics.sentiment_client import SentimentClient
        _log(creator_id, "scrape", "info", "Waking sentiment engine (HF Space cold-start)...")
        warmed = asyncio.run(SentimentClient().warmup())
        _log(creator_id, "scrape", "ok" if warmed else "warn",
             "Sentiment engine ready" if warmed else "Sentiment engine warmup timed out — will retry per batch")
    except Exception as exc:
        _log(creator_id, "scrape", "warn", f"Sentiment warmup error (non-fatal): {exc}")

    _log(creator_id, "scrape", "info", f"Fanning out {len(posts)} post tasks in parallel...")

    # Use a Redis counter instead of a chord — chord silently aborts if any single
    # task fails (502, timeout, etc.) and finalize_creator never runs.
    _init_counter(creator_id, len(posts))

    group(
        scrape_and_process_post.s(p["url"], p["external_id"], info["platform"], creator_id, {
            "likes":           p.get("likes", 0),
            "views":           p.get("views", 0),
            "shares":          p.get("shares", 0),
            "comment_count":   p.get("comment_count", 0),
            "caption":         p.get("caption", ""),
            "tags":            p.get("tags", []),
            "posted_at":       p.get("posted_at"),
            "media_type":      p.get("media_type", 1),
            "is_collab":       p.get("is_collab", 0),
            "counts_disabled": p.get("counts_disabled", 0),
            "thumbnail_url":   p.get("thumbnail_url", ""),
        })
        for p in posts
    ).delay()

    return {"discovered": len(posts)}


# ── Task 2: scrape one post + ETL + sentiment ─────────────────────────────────

@celery_app.task(bind=True, name="workers.tasks.scrape_and_process_post")
def scrape_and_process_post(self, url: str, external_id: str, platform: str, creator_id: int, post_metadata: dict = None):
    def _done():
        """Decrement counter and fire finalize when last task completes."""
        remaining = _decr_counter(creator_id)
        if remaining == 0:
            _log(creator_id, "finalize", "info", "All post tasks complete — starting finalize")
            finalize_creator.delay([], creator_id)

    return _scrape_and_process_post_inner(self, url, external_id, platform, creator_id, post_metadata, _done)


def _scrape_and_process_post_inner(self, url, external_id, platform, creator_id, post_metadata, _done):
    if _is_stopped(creator_id):
        _done()
        return {"skipped": True, "reason": "stopped"}

    # Stagger parallel Instagram requests so the same session isn't hit simultaneously.
    if platform == "instagram":
        time.sleep(random.uniform(0.5, 3))

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

        meta = post_metadata or {}
        posted_at = None
        if meta.get("posted_at"):
            try:
                posted_at = datetime.fromtimestamp(float(meta["posted_at"]), tz=timezone.utc)
            except (TypeError, ValueError, OSError):
                pass

        existing = db.query(Post).filter(Post.external_id == external_id).first()
        if existing:
            if existing.etl_status in ("transformed", "analyzed"):
                # Re-associate with a different creator if needed
                if existing.creator_id != creator_id:
                    existing.creator_id = creator_id
                    if campaign_id:
                        existing.campaign_id = campaign_id
                    db.commit()
                    _log(creator_id, "scrape", "info", f"Re-associated post from old creator record: {short_url}")
                    _done()
                    return {"post_id": existing.id, "skipped": True}

                # Backfill thumbnail and view count if we now have better data
                updated = False
                if meta.get("thumbnail_url") and not existing.thumbnail_url:
                    existing.thumbnail_url = meta["thumbnail_url"]
                    updated = True
                if meta.get("views") and not existing.views:
                    existing.views = meta["views"]
                    updated = True
                if updated:
                    db.commit()

                # Re-scrape if the stored comment count is much lower than reported
                # (catches posts scraped before reply-fetching was implemented)
                from app.models.comment import Comment as _Cmt
                stored_count = db.query(_Cmt).filter(_Cmt.post_id == existing.id).count()
                expected = existing.comment_count or 0
                needs_rescrape = expected > 0 and stored_count < expected * 0.5
                if not needs_rescrape:
                    _log(creator_id, "scrape", "info",
                         f"Skipped (already processed, {stored_count}/{expected} comments): {short_url}")
                    _done()
                    return {"post_id": existing.id, "skipped": True}
                _log(creator_id, "scrape", "info",
                     f"Re-scraping: only {stored_count}/{expected} comments in DB for {short_url}")
            _log(creator_id, "scrape", "info", f"Re-processing unfinished post: {short_url}")
            post_id = existing.id
            existing.etl_status = "pending"
            # Update metadata fields if we now have better data
            if meta.get("likes"):
                existing.likes = meta["likes"]
            if meta.get("views"):
                existing.views = meta["views"]
            if meta.get("shares"):
                existing.shares = meta["shares"]
            if meta.get("comment_count"):
                existing.comment_count = meta["comment_count"]
            if meta.get("caption"):
                existing.caption = meta["caption"]
            if meta.get("tags"):
                import json as _json
                existing.tags = _json.dumps(meta["tags"])
            if meta.get("media_type"):
                existing.media_type = meta["media_type"]
            existing.is_collab = meta.get("is_collab", 0)
            existing.counts_disabled = meta.get("counts_disabled", 0)
            if meta.get("thumbnail_url"):
                existing.thumbnail_url = _save_thumbnail(meta["thumbnail_url"], platform, external_id)
            if posted_at:
                existing.posted_at = posted_at
            db.commit()
        else:
            import json as _json
            post = Post(
                platform_id=platform_obj.id,
                campaign_id=campaign_id,
                creator_id=creator_id,
                external_id=external_id,
                url=url,
                likes=meta.get("likes", 0),
                views=meta.get("views", 0),
                shares=meta.get("shares", 0),
                comment_count=meta.get("comment_count", 0),
                caption=meta.get("caption", ""),
                tags=_json.dumps(meta.get("tags", [])),
                media_type=meta.get("media_type", 1),
                is_collab=meta.get("is_collab", 0),
                counts_disabled=meta.get("counts_disabled", 0),
                thumbnail_url=_save_thumbnail(meta.get("thumbnail_url", ""), platform, external_id),
                posted_at=posted_at,
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
            "youtube":   "scraping.youtube.YouTubeScraper",
        }
        module_path, cls_name = scraper_map[platform].rsplit(".", 1)
        mod = __import__(module_path, fromlist=[cls_name])
        scraper = getattr(mod, cls_name)()
        jsonl_path = asyncio.run(scraper.scrape(url, creator_id=creator_id))
        _log(creator_id, "scrape", "ok", f"Scraped → {jsonl_path}")
    except Exception as exc:
        _log(creator_id, "scrape", "error", f"Scraper crashed on {short_url}: {exc}")
        _update_post_status(post_id, "scrape_failed")
        _done()
        return {"post_id": post_id, "error": str(exc)}

    _update_post_status(post_id, "scraped", raw_data_path=str(jsonl_path))

    # ── YouTube: extract video-level metadata and persist to DB ──────────────
    # YouTubeScraper writes view_count, like_count, channel_follower_count, thumbnail,
    # etc. as the first JSONL record (__type == "meta"). Pull it back and save it so
    # the matching engine can use views/likes/avatar without waiting for a re-scrape.
    if platform == "youtube" and jsonl_path.exists():
        try:
            from etl.cleaners.youtube_cleaner import YouTubeCleaner as _YTCleaner
            from app.models.creator import Creator as _Creator
            yt_meta = _YTCleaner().extract_post_metadata(jsonl_path)
            if yt_meta:
                _db = get_sync_db()
                try:
                    _post = _db.get(Post, post_id)
                    if _post:
                        if yt_meta.get("view_count") is not None:
                            _post.views = int(yt_meta["view_count"])
                        if yt_meta.get("like_count") is not None:
                            _post.likes = int(yt_meta["like_count"])
                        if yt_meta.get("comment_count") is not None:
                            _post.comment_count = int(yt_meta["comment_count"])
                        if yt_meta.get("description"):
                            _post.caption = yt_meta["description"] or ""
                        if yt_meta.get("tags"):
                            import json as _json2
                            _post.tags = _json2.dumps(yt_meta["tags"])
                        if yt_meta.get("upload_date"):
                            try:
                                d = str(yt_meta["upload_date"])  # "YYYYMMDD"
                                _post.posted_at = datetime(
                                    int(d[:4]), int(d[4:6]), int(d[6:8]), tzinfo=timezone.utc
                                )
                            except Exception:
                                pass
                        # Video thumbnail from yt-dlp full extract (reliable)
                        if yt_meta.get("thumbnail") and not _post.thumbnail_url:
                            _post.thumbnail_url = yt_meta["thumbnail"]
                    _creator = _db.get(_Creator, creator_id)
                    if _creator:
                        if yt_meta.get("channel_follower_count"):
                            _creator.follower_count = int(yt_meta["channel_follower_count"])
                        if yt_meta.get("channel") and not _creator.display_name:
                            _creator.display_name = yt_meta["channel"]
                        bio = (yt_meta.get("channel_description") or "").strip()
                        if bio and not _creator.bio:
                            _creator.bio = bio
                    _db.commit()
                    v = yt_meta.get("view_count", 0) or 0
                    l = yt_meta.get("like_count", 0) or 0
                    subs = yt_meta.get("channel_follower_count", "?")
                    _log(creator_id, "etl", "ok",
                         f"YouTube meta saved: views={v:,} likes={l:,} subs={subs}")
                except Exception as _exc:
                    _db.rollback()
                    _log(creator_id, "etl", "warn", f"YouTube meta DB save failed (non-fatal): {_exc}")
                finally:
                    _db.close()
        except Exception as _exc:
            _log(creator_id, "etl", "warn", f"YouTube meta extraction failed (non-fatal): {_exc}")

    if not jsonl_path.exists() or jsonl_path.stat().st_size == 0:
        _log(creator_id, "etl", "warn",
             f"0 comments captured for {short_url} — JSONL empty (bot detection, no comments, or session issue)")
        _update_post_status(post_id, "etl_failed")
        _done()
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
        _done()
        return {"post_id": post_id, "error": str(exc)}

    if not raw_comments:
        _update_post_status(post_id, "etl_failed")
        _done()
        return {"post_id": post_id, "error": "0 comments extracted"}

    # ── Store comments ──
    _log(creator_id, "etl", "info", "Saving comments to DB...")
    try:
        from app.models.comment import Comment
        from app.models.post import Post as PostModel
        db = get_sync_db()
        try:
            # One batch query to get all already-stored external_ids for this post
            existing_ids: set = {
                row[0]
                for row in db.query(Comment.external_id)
                .filter(Comment.post_id == post_id)
                .all()
            }

            # Build new Comment objects without any per-row queries (avoids autoflush lock)
            new_comments = []
            seen_in_batch: set = set()
            for raw in raw_comments:
                ext_id = raw.get("external_id", "")
                if ext_id in existing_ids or ext_id in seen_in_batch:
                    continue
                seen_in_batch.add(ext_id)
                new_comments.append(Comment(
                    post_id=post_id,
                    external_id=ext_id,
                    author=pseudonymize(raw.get("author", "")),   # RGPD: pseudonymise at ingestion
                    raw_text=raw["raw_text"],
                    cleaned_text=raw["raw_text"],
                    language="raw",
                    likes=raw.get("likes", 0),
                    posted_at=raw.get("posted_at"),
                ))

            if new_comments:
                db.add_all(new_comments)
            stored = len(new_comments)

            # For YouTube: read the meta record from JSONL to update post stats
            if platform == "youtube":
                try:
                    from etl.cleaners.youtube_cleaner import YouTubeCleaner
                    yt_meta = YouTubeCleaner().extract_post_metadata(jsonl_path)
                    if yt_meta:
                        post_obj = db.get(PostModel, post_id)
                        if post_obj:
                            if yt_meta.get("view_count") is not None:
                                post_obj.views = int(yt_meta["view_count"])
                            if yt_meta.get("like_count") is not None:
                                post_obj.likes = int(yt_meta["like_count"])
                            if yt_meta.get("comment_count") is not None:
                                post_obj.comment_count = int(yt_meta["comment_count"])
                            if yt_meta.get("description"):
                                post_obj.caption = yt_meta["description"]
                            if yt_meta.get("tags"):
                                import json as _json3
                                post_obj.tags = _json3.dumps(yt_meta["tags"])
                            if yt_meta.get("upload_date"):
                                try:
                                    post_obj.posted_at = datetime.strptime(
                                        yt_meta["upload_date"], "%Y%m%d"
                                    ).replace(tzinfo=timezone.utc)
                                except ValueError:
                                    pass
                            if yt_meta.get("thumbnail") and not post_obj.thumbnail_url:
                                post_obj.thumbnail_url = yt_meta["thumbnail"]
                        from app.models.creator import Creator as CreatorModel
                        creator_obj = db.get(CreatorModel, creator_id)
                        if creator_obj:
                            if yt_meta.get("channel_follower_count"):
                                creator_obj.follower_count = int(yt_meta["channel_follower_count"])
                            if yt_meta.get("channel") and not creator_obj.display_name:
                                creator_obj.display_name = yt_meta["channel"]
                            bio = (yt_meta.get("channel_description") or "").strip()
                            if bio and not creator_obj.bio:
                                creator_obj.bio = bio
                        _log(creator_id, "etl", "info",
                             f"YouTube meta: views={yt_meta.get('view_count')} "
                             f"likes={yt_meta.get('like_count')} "
                             f"subs={yt_meta.get('channel_follower_count')}")
                except Exception as exc:
                    _log(creator_id, "etl", "warn", f"YouTube meta update failed (non-fatal): {exc}")

            # Commit with retry for transient lock contention
            for attempt in range(4):
                try:
                    db.commit()
                    break
                except Exception as commit_exc:
                    if "database is locked" in str(commit_exc) and attempt < 3:
                        db.rollback()
                        time.sleep(1 + attempt * 2)
                    else:
                        raise

            _log(creator_id, "etl", "ok", f"Stored {stored} new comment(s) in DB")

            # Update post.comment_count to the real total (top-level + replies)
            actual_total = db.query(Comment).filter(Comment.post_id == post_id).count()
            post_obj = db.get(PostModel, post_id)
            if post_obj and actual_total > (post_obj.comment_count or 0):
                post_obj.comment_count = actual_total
                db.commit()
        finally:
            db.close()
        _update_post_status(post_id, "transformed")
    except Exception as exc:
        _log(creator_id, "etl", "error", f"DB store failed: {exc}")
        _update_post_status(post_id, "etl_failed")
        _done()
        return {"post_id": post_id, "error": str(exc)}

    # ── Sentiment ──
    _log(creator_id, "sentiment", "info",
         f"Sending to AI engine ({settings.AI_ENGINE_URL}) in batches of 50...")
    try:
        from app.models.comment import Comment
        from analytics.sentiment_client import SentimentClient
        from sqlalchemy import update as sql_update

        # Load only id + text — never keep ORM objects alive across sessions
        db = get_sync_db()
        try:
            rows = db.query(Comment.id, Comment.cleaned_text, Comment.raw_text).filter(
                Comment.post_id == post_id,
                Comment.sentiment == None,
            ).all()
        finally:
            db.close()

        if rows:
            comment_ids = [r[0] for r in rows]
            texts = [r[1] or r[2] for r in rows]

            client = SentimentClient()
            results = asyncio.run(client.analyze(texts))

            now = datetime.now(timezone.utc)
            db = get_sync_db()
            try:
                for cid, result in zip(comment_ids, results):
                    if result:
                        db.execute(
                            sql_update(Comment)
                            .where(Comment.id == cid)
                            .values(
                                sentiment=result.label,
                                sentiment_score=result.score,
                                sentiment_confidence=result.confidence,
                                analyzed_at=now,
                            )
                            .execution_options(synchronize_session=False)
                        )
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

    _done()
    return {"post_id": post_id, "done": True}


# ── Task 3: finalize ──────────────────────────────────────────────────────────

@celery_app.task(name="workers.tasks.finalize_creator")
def finalize_creator(results, creator_id: int):
    from app.models.creator import Creator
    from app.models.post import Post
    from app.models.comment import Comment
    from analytics.topics_engine import extract_topics_with_ai

    _log(creator_id, "finalize", "info", "All posts processed — aggregating stats...")

    db = get_sync_db()
    try:
        creator = db.get(Creator, creator_id)
        if not creator:
            return

        posts = db.query(Post).filter(Post.creator_id == creator_id).all()
        post_ids = [p.id for p in posts]
        comments = db.query(Comment).filter(Comment.post_id.in_(post_ids)).all() if post_ids else []

        total    = len(comments)
        positive = sum(1 for c in comments if c.sentiment == "positive")
        negative = sum(1 for c in comments if c.sentiment == "negative")
        neutral  = sum(1 for c in comments if c.sentiment == "neutral")
        analyzed = positive + negative + neutral
        avg_score = (
            sum(c.sentiment_score for c in comments if c.sentiment_score is not None) / analyzed
            if analyzed > 0 else 0.0
        )

        texts = [c.cleaned_text or c.raw_text for c in comments if c.cleaned_text or c.raw_text]
        _log(creator_id, "finalize", "info",
             f"Extracting topics from {len(texts)} comments via Qwen2.5 (Ollama)...")
        top_topics = extract_topics_with_ai(texts, top_n=10)

        if analyzed == 0:
            mood = "unknown"
        elif positive / analyzed > 0.6:
            mood = "happy"
        elif negative / analyzed > 0.4:
            mood = "angry"
        else:
            mood = "mixed"

        creator.total_posts_scraped = len(posts)
        creator.total_comments = total
        creator.positive_pct = round(positive / max(analyzed, 1) * 100, 1)
        creator.negative_pct = round(negative / max(analyzed, 1) * 100, 1)
        creator.neutral_pct = round(neutral  / max(analyzed, 1) * 100, 1)
        creator.avg_sentiment_score = round(avg_score, 4)
        creator.top_topics = top_topics
        creator.audience_mood = mood
        creator.status = "done"
        creator.last_pipeline_at = datetime.now(timezone.utc)

        # ── Generate embedding for matching ──
        _log(creator_id, "finalize", "info", "Generating content embedding for matching...")
        try:
            from analytics.embedding_service import EmbeddingService
            from app.models.platform import Platform
            import re as _re
            _HTAG_RE = _re.compile(r"#(\w+)")
            # Compute post-level signals for a richer embedding
            n_posts = len(posts)
            total_views_emb = sum(p.views or 0 for p in posts)
            total_likes_emb = sum(p.likes or 0 for p in posts)
            total_cmts_emb  = sum(p.comment_count or 0 for p in posts)
            avg_views_emb   = total_views_emb / n_posts if n_posts else 0.0
            avg_likes_emb   = total_likes_emb / n_posts if n_posts else 0.0
            avg_cmts_emb    = total_cmts_emb  / n_posts if n_posts else 0.0
            if avg_views_emb > 0:
                eng_rate_emb = min((avg_likes_emb + avg_cmts_emb) / avg_views_emb * 100, 100.0)
            elif avg_likes_emb > 0:
                eng_rate_emb = min(avg_cmts_emb / avg_likes_emb * 100, 20.0)
            else:
                eng_rate_emb = 0.0
            # Extract top hashtags from captions
            ht_counts: dict = {}
            for p in posts:
                for h in _HTAG_RE.findall(p.caption or ""):
                    ht_counts[h.lower()] = ht_counts.get(h.lower(), 0) + 1
            top_hashtags_emb = [h for h, _ in sorted(ht_counts.items(), key=lambda x: -x[1])[:12]]
            # Get platform name
            platform_obj = db.get(Platform, creator.platform_id)
            platform_name_emb = platform_obj.name if platform_obj else "unknown"

            svc = EmbeddingService()
            topic_names = [t["topic"] for t in top_topics] if top_topics else []
            summary = svc.build_creator_text(
                creator.username, creator.bio, topic_names, mood,
                hashtags=top_hashtags_emb,
                platform=platform_name_emb,
                follower_count=creator.follower_count or 0,
                avg_views=avg_views_emb,
                engagement_rate=eng_rate_emb,
            )
            embedding = svc.generate_embedding(summary)
            if embedding:
                creator.content_summary = summary
                creator.content_embedding = json.dumps(embedding)
                _log(creator_id, "finalize", "ok",
                     f"Embedding generated ({len(embedding)} dimensions)")
            else:
                _log(creator_id, "finalize", "warn", "Embedding generation returned empty")
        except Exception as exc:
            _log(creator_id, "finalize", "warn", f"Embedding generation failed (non-fatal): {exc}")

        db.commit()

        _log(creator_id, "finalize", "ok",
             f"Done — {len(posts)} posts, {total} comments, mood: {mood} "
             f"({positive} pos / {negative} neg / {neutral} neutral)")

        # ── Auto-refresh matching cache for all campaigns ──
        try:
            from analytics.matching_engine import compute_and_cache_all
            refreshed = asyncio.run(compute_and_cache_all(_redis))
            _log(creator_id, "finalize", "ok",
                 f"Matching scores refreshed for {refreshed} campaign(s)")
        except Exception as exc:
            _log(creator_id, "finalize", "warn",
                 f"Auto-matching cache failed (non-fatal): {exc}")
    finally:
        db.close()

@celery_app.task
def purge_old_comments_task():
    """RGPD retention (Art. 5(1)(e)): delete comments past the retention window."""
    from app.core.privacy import purge_old_comments
    db = get_sync_db()
    try:
        n = purge_old_comments(db)
        logger.info("RGPD retention: purged %d old comment(s)", n)
        return n
    finally:
        db.close()
