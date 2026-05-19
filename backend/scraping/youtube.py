"""
YouTube comment scraper using yt-dlp.
No browser needed — yt-dlp handles YouTube's API and anti-bot measures internally.
"""
import asyncio
import logging
import re
from pathlib import Path

import yt_dlp

from scraping.base import BaseScraper

logger = logging.getLogger(__name__)

_VIDEO_RE = re.compile(r"(?:v=|youtu\.be/)([A-Za-z0-9_-]{11})")


class _YTLogger:
    """Routes yt-dlp output to our Python logger so errors are visible in Celery logs."""
    def debug(self, msg):
        logger.debug("yt-dlp: %s", msg)

    def info(self, msg):
        logger.info("yt-dlp: %s", msg)

    def warning(self, msg):
        logger.warning("yt-dlp: %s", msg)

    def error(self, msg):
        logger.error("yt-dlp: %s", msg)


class YouTubeScraper(BaseScraper):
    platform = "youtube"

    async def scrape(self, url: str, max_comments: int = 200, **kwargs) -> Path:
        m = _VIDEO_RE.search(url)
        video_id = m.group(1) if m else "unknown"
        out_path = self._get_output_path(video_id)

        ydl_opts = {
            "skip_download": True,
            "getcomments": True,
            "ignore_no_formats_error": True,
            "extractor_args": {
                "youtube": {
                    "comment_sort": ["top"],
                    # [max_comments, max_parents, max_replies, max_replies_per_thread]
                    "max_comments": [str(max_comments), str(max_comments), "0", "0"],
                }
            },
            "logger": _YTLogger(),
            "quiet": False,
            "no_warnings": False,
        }

        def _extract():
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                return ydl.extract_info(url, download=False)

        loop = asyncio.get_running_loop()
        try:
            info = await loop.run_in_executor(None, _extract)
        except Exception as exc:
            logger.error("yt-dlp failed for %s: %s", url, exc)
            return out_path

        if not info:
            logger.warning("yt-dlp returned None for %s", video_id)
            return out_path

        # Save video-level metadata as the first record (type=meta)
        meta = {
            "__type":               "meta",
            "view_count":           info.get("view_count"),
            "like_count":           info.get("like_count"),
            "comment_count":        info.get("comment_count"),
            "duration":             info.get("duration"),
            "description":          (info.get("description") or "")[:1000],
            "upload_date":          info.get("upload_date"),        # "YYYYMMDD"
            "channel":              info.get("channel"),
            "channel_id":           info.get("channel_id"),
            "uploader_id":          info.get("uploader_id"),        # @handle
            "channel_follower_count": info.get("channel_follower_count"),
            "thumbnail":            info.get("thumbnail"),
            "tags":                 (info.get("tags") or [])[:20],
            "categories":           info.get("categories") or [],
        }
        self._append_record(out_path, meta, video_id)
        logger.info(
            "YouTube %s: views=%s likes=%s subscribers=%s",
            video_id, meta["view_count"], meta["like_count"], meta["channel_follower_count"],
        )

        comments = info.get("comments") or []
        logger.info(
            "YouTube %s: yt-dlp returned %d comment(s) ('comments' key present: %s)",
            video_id, len(comments), "comments" in info,
        )

        for comment in comments:
            self._append_record(out_path, comment, video_id)

        logger.info("YouTube: saved %d comments → %s", len(comments), out_path)
        return out_path
