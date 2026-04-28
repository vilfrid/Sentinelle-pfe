"""
Transforms Tunisian Arabizi (Franco-Arab) text to Arabic script using Gemma 3 27B.
Refactored from test/tra.py — now class-based with configurable settings.
"""
import json
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

Process each text in the input array according to these rules:
1. If the text is purely French, English, Italian, or another non-Arabic/non-Darija language → return exactly the string: {ignore}
2. If the text is Tunisian Arabizi (Franco-Arab mix, uses 3/7/9/5 as Arabic letters) → convert it to Arabic script
   - Keep French/English loanwords phonetically in Arabic (e.g. "Bravo" → "برافو")
   - Preserve emojis
3. If the text is already Arabic script → return it as-is

Input JSON array:
{lines}

Reply with ONLY a valid JSON array of strings, one output per input, in the same order.
No explanation, no markdown, no code block — just the raw JSON array."""


class ArabiziTransformer:
    def __init__(self):
        genai.configure(api_key=settings.GOOGLE_API_KEY)
        self.model = genai.GenerativeModel("gemma-3-27b-it")

    def _build_prompt(self, lines: List[str]) -> str:
        return _PROMPT_TEMPLATE.format(
            ignore=_IGNORE,
            lines=json.dumps(lines, ensure_ascii=False),
        )

    def _parse_response(self, text: str, count: int) -> List[str]:
        # Strip markdown code fences if present
        clean = re.sub(r"```(?:json)?\s*|\s*```", "", text).strip()
        try:
            parsed = json.loads(clean)
            if isinstance(parsed, list) and len(parsed) == count:
                return [str(r).strip() for r in parsed]
            logger.warning("JSON response length mismatch: got %d, expected %d", len(parsed), count)
            # Pad or truncate to match count
            result = [str(r).strip() for r in parsed]
            while len(result) < count:
                result.append("")
            return result[:count]
        except json.JSONDecodeError:
            logger.warning("JSON parse failed. Raw response snippet: %r", text[:300])
            return [""] * count

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
                parsed = self._parse_response(response.text, len(batch))
                filled = sum(1 for r in parsed if r)
                logger.info("Arabizi batch: %d/%d lines parsed successfully", filled, len(batch))
                return parsed
            except (ResourceExhausted, ServiceUnavailable, InternalServerError) as e:
                logger.warning("API error (attempt %d/%d): %s", attempt + 1, _RETRY_ATTEMPTS, e)
                if attempt < _RETRY_ATTEMPTS - 1:
                    delay_match = re.search(r"retry[_ ](?:after|in)[_ ](\d+(?:\.\d+)?)", str(e), re.IGNORECASE)
                    wait = float(delay_match.group(1)) + 5 if delay_match else _RETRY_DELAY * (attempt + 1) * 4
                    logger.info("Waiting %.0fs before retry…", wait)
                    time.sleep(wait)
            except Exception as e:
                logger.error("Unexpected error in transformer: %s", e)
                break
        return [""] * len(batch)

    def is_ignored(self, text: str) -> bool:
        return text.strip() == _IGNORE
