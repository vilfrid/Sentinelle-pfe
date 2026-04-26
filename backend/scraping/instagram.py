"""
Instagram comment scraper using Playwright.
Intercepts the PolarisPostCommentsPaginationQuery GraphQL endpoint.
"""
import asyncio
import json
import logging
import re
from pathlib import Path

from playwright.async_api import async_playwright, Request
from scraping.base import BaseScraper
from app.config import settings

logger = logging.getLogger(__name__)

_GRAPHQL_QUERY = "PolarisPostCommentsPaginationQuery"
_POST_RE = re.compile(r"/p/([A-Za-z0-9_-]+)/")
_REEL_RE = re.compile(r"/reel/([A-Za-z0-9_-]+)/")


class InstagramScraper(BaseScraper):
    platform = "instagram"

    async def scrape(self, url: str, session_id: str = "", **kwargs) -> Path:
        session_id = session_id or settings.INSTAGRAM_SESSION_ID
        m = _REEL_RE.search(url) or _POST_RE.search(url)
        post_id = m.group(1) if m else url.split("/")[-2]
        post_type = "reels" if _REEL_RE.search(url) else "posts"
        out_path = self._get_output_path(f"{post_type}_{post_id}")
        captured: list[dict] = []

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            ctx = await browser.new_context()
            await ctx.add_cookies([{
                "name": "sessionid", "value": session_id,
                "domain": ".instagram.com", "path": "/",
            }])
            page = await ctx.new_page()

            async def handle_request(request: Request):
                if _GRAPHQL_QUERY in request.url:
                    try:
                        resp = await request.response()
                        if resp:
                            body = await resp.json()
                            self._append_record(out_path, body, post_id)
                            captured.append(body)
                    except Exception:
                        pass

            page.on("request", handle_request)
            await page.goto(url, wait_until="networkidle", timeout=30_000)

            for _ in range(5):
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await asyncio.sleep(2)
                try:
                    btn = await page.query_selector("button[aria-label='Load more comments']")
                    if btn:
                        await btn.click()
                        await asyncio.sleep(1.5)
                except Exception:
                    pass

            await browser.close()

        logger.info("Instagram: saved %d batches → %s", len(captured), out_path)
        return out_path
