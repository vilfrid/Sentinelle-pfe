"""
Facebook comment scraper using Playwright.
Intercepts GraphQL comment query responses.
"""
import asyncio
import logging
import re
from pathlib import Path

from playwright.async_api import async_playwright
from scraping.base import BaseScraper

logger = logging.getLogger(__name__)

_FB_GRAPHQL = "/api/graphql/"
_POST_RE = re.compile(r"/posts/(\d+)|permalink/(\d+)|story_fbid=(\d+)")


class FacebookScraper(BaseScraper):
    platform = "facebook"

    async def scrape(self, url: str, cookies: list[dict] | None = None, **kwargs) -> Path:
        m = _POST_RE.search(url)
        post_id = next((g for g in (m.groups() if m else []) if g), url.split("/")[-1])
        out_path = self._get_output_path(post_id)
        captured = 0

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            ctx = await browser.new_context()
            if cookies:
                await ctx.add_cookies(cookies)
            page = await ctx.new_page()

            async def intercept(response):
                nonlocal captured
                if _FB_GRAPHQL in response.url:
                    try:
                        text = await response.text()
                        for line in text.splitlines():
                            if '"node"' in line and '"message"' in line:
                                import json
                                body = json.loads(line)
                                self._append_record(out_path, body, post_id)
                                captured += 1
                                break
                    except Exception:
                        pass

            page.on("response", intercept)
            await page.goto(url, wait_until="networkidle", timeout=30_000)
            await asyncio.sleep(3)

            for _ in range(10):
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await asyncio.sleep(2)

            await browser.close()

        logger.info("Facebook: saved %d records → %s", captured, out_path)
        return out_path
