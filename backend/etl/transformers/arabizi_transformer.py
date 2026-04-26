"""
Transforms Tunisian Arabizi (Franco-Arab) text to Arabic script using Gemma 3 27B.
Refactored from test/tra.py — now class-based with configurable settings.
"""
import asyncio
import logging
import re
import time
from typing import List

import google.generativeai as genai
from google.api_core.exceptions import ResourceExhausted, ServiceUnavailable, InternalServerError

from app.config import settings

logger = logging.getLogger(__name__)

_IGNORE = "[IGNORE]"
_BATCH_SIZE = 12
_RETRY_ATTEMPTS = 3
_RETRY_DELAY = 10
_RATE_DELAY = 2.5

_PROMPT_TEMPLATE = """You are an expert in Tunisian dialect (Darija) and Arabizi transliteration.

Process each line according to these rules:
1. If the line is purely French, English, Italian, or another foreign language (no Arabizi/Darija) → output exactly: {ignore}
2. If the line is Tunisian Arabizi (uses 3, 7, 9, 5 as Arabic letters, Franco-Arab mix) → transmute it to Arabic script
   - Keep French/English loanwords phonetically in Arabic (e.g. "Bravo" → "برافو")
   - Preserve emojis
3. If the line is already Arabic → return it as-is

Input lines:
{lines}

Output each result on its own line prefixed with LINE_X: (where X is the 1-based line number).
Do not add any other commentary."""


class ArabiziTransformer:
    def __init__(self):
        genai.configure(api_key=settings.GOOGLE_API_KEY)
        self.model = genai.GenerativeModel("gemma-3-27b-it")

    def _build_prompt(self, lines: List[str]) -> str:
        formatted = "\n".join(f"LINE_{i+1}: {line}" for i, line in enumerate(lines))
        return _PROMPT_TEMPLATE.format(ignore=_IGNORE, lines=formatted)

    def _parse_response(self, text: str, count: int) -> List[str]:
        results = [""] * count
        for match in re.finditer(r"LINE_(\d+):\s*(.*)", text):
            idx = int(match.group(1)) - 1
            if 0 <= idx < count:
                results[idx] = match.group(2).strip()
        return results

    def transform_batch(self, lines: List[str]) -> List[str]:
        results = []
        for i in range(0, len(lines), _BATCH_SIZE):
            batch = lines[i: i + _BATCH_SIZE]
            batch_result = self._transform_single_batch(batch)
            results.extend(batch_result)
            time.sleep(_RATE_DELAY)
        return results

    def _transform_single_batch(self, batch: List[str]) -> List[str]:
        prompt = self._build_prompt(batch)
        for attempt in range(_RETRY_ATTEMPTS):
            try:
                response = self.model.generate_content(prompt)
                return self._parse_response(response.text, len(batch))
            except (ResourceExhausted, ServiceUnavailable, InternalServerError) as e:
                logger.warning("API error (attempt %d/%d): %s", attempt + 1, _RETRY_ATTEMPTS, e)
                if attempt < _RETRY_ATTEMPTS - 1:
                    time.sleep(_RETRY_DELAY * (attempt + 1))
            except Exception as e:
                logger.error("Unexpected error in transformer: %s", e)
                break
        return [""] * len(batch)

    def is_ignored(self, text: str) -> bool:
        return text.strip() == _IGNORE
