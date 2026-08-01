"""
Trending topics extraction for Arabic/Arabizi/French/English social media comments.

Extraction priority:
  1. HF Space  (HF_SPACE_URL in settings) — Qwen2.5-7B via InferenceClient, real semantic clustering
  2. Word-freq                             — always available, no AI required
"""
import re
import logging
from collections import Counter
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)

_HF_TIMEOUT      = 90    # max per-batch request to topics Space (Qwen on CPU needs time)
_HF_WARMUP_TIMEOUT = 30  # if not ready in 30s, fall back to word-freq

_STOPWORDS_AR = {
    "في", "من", "على", "إلى", "عن", "مع", "هذا", "هذه", "التي", "الذي",
    "كان", "كانت", "يكون", "تكون", "وأن", "أنا", "أنت", "هو", "هي",
    "نحن", "هم", "هل", "لا", "ما", "لم", "لن", "قد", "إن", "أن",
    "و", "أو", "ثم", "لكن", "بل", "حتى", "كل", "كيف", "متى", "اين",
    "كنت", "انت", "هاذا", "هاذه", "يعني", "بيه", "عليه", "منه", "فيه",
    "ليه", "عليك", "منك", "ليك", "بيك", "عليها", "منها", "ليها",
    "اللي", "هاك", "هيا", "اي", "مش", "مو", "ولا", "واش", "علاش",
    "برشا", "شوية", "بالله", "ربي", "يا", "اه", "اي",
}

_STOPWORDS_EN = {
    "the", "and", "for", "that", "this", "with", "have", "from", "they",
    "will", "been", "were", "are", "was", "has", "had", "but", "not",
    "you", "your", "all", "can", "her", "his", "him", "she", "its",
    "one", "our", "out", "who", "more", "also", "what", "when", "their",
    "there", "about", "which", "into", "than", "then", "them", "these",
    "those", "just", "some", "would", "could", "should", "very", "such",
    "even", "well", "get", "got", "let", "like", "see", "now", "how",
    "any", "may", "use", "new", "too", "way", "why", "did", "two",
    "its", "own", "over", "said", "each", "most", "both", "being",
    "after", "before", "same", "while", "much", "other", "take",
    "only", "come", "good", "know", "make", "look", "time", "here",
    "think", "give", "still", "back", "never", "need", "want", "going",
    "feel", "nice", "love", "great", "best", "really", "actually",
    "already", "always", "please", "thank", "thanks", "yes", "yeah",
    "nope", "okay", "omg", "lol", "bro", "man", "wow", "hey",
    "link", "bio", "post", "page", "story", "video", "photo", "photo",
    "comment", "comments", "follow", "followers", "following", "like",
    "share", "shares", "view", "views", "watch", "subscribe",
    "official", "account", "profile", "check", "visit", "new",
}

_STOPWORDS_FR = {
    "les", "des", "une", "est", "que", "pour", "dans", "par", "sur",
    "avec", "son", "ses", "leur", "leurs", "aux", "mais", "pas", "plus",
    "sont", "ont", "une", "tout", "cette", "ces", "cela", "aussi",
    "comme", "bien", "tres", "qui", "quoi", "quel", "elle", "elles",
    "ils", "nous", "vous", "votre", "notre", "moi", "toi", "lui",
    "mon", "ton", "mes", "tes", "peut", "fait", "faire", "svp",
    "merci", "bonjour", "bonsoir", "stp", "sil", "vous", "plaît",
    "tres", "trop", "vraiment", "encore", "toujours", "jamais",
}

_STOPWORDS_MISC = {
    # Arabic-script function words (repeated for safety)
    "و",
    # Social media noise
    "via", "amp", "http", "https", "www", "com", "net", "org",
    # Common short filler
    "lol", "omg", "wtf", "tbh",
}

_ALL_STOPS = _STOPWORDS_AR | _STOPWORDS_EN | _STOPWORDS_FR | _STOPWORDS_MISC
_MIN_WORD_LEN = 3
_MIN_COUNT = 2  # preferred minimum; relaxed to 1 for small datasets

# Strip URLs and @mentions before tokenizing
_CLEAN_RE = re.compile(r"https?://\S+|@\w+", re.IGNORECASE)


def extract_trending_topics(texts: List[str], top_n: int = 20) -> List[Dict]:
    word_counts: Counter = Counter()
    for text in texts:
        clean = _CLEAN_RE.sub(" ", text)
        words = re.findall(r"[؀-ۿa-zA-Z]{3,}", clean)
        for word in words:
            w = word.lower()
            if len(w) >= _MIN_WORD_LEN and w not in _ALL_STOPS:
                word_counts[w] += 1

    threshold = _MIN_COUNT
    result = [
        {"topic": word, "count": count}
        for word, count in word_counts.most_common(top_n)
        if count >= threshold
    ]
    # For small datasets every word may appear only once; relax the threshold.
    if not result and word_counts:
        result = [
            {"topic": word, "count": count}
            for word, count in word_counts.most_common(top_n)
        ]
    return result


def extract_hashtags(texts: List[str]) -> List[Dict]:
    tag_counts: Counter = Counter()
    for text in texts:
        for tag in re.findall(r"#\w+", text):
            tag_counts[tag.lower()] += 1
    return [
        {"hashtag": tag, "count": count}
        for tag, count in tag_counts.most_common(15)
    ]


_HF_BATCH_SIZE   = 20    # comments per request to the HF Space (smaller = faster Qwen inference)
_HF_MAX_BATCHES  = 15    # process up to 300 comments (shuffled for representative sampling)
_HF_MAX_CHARS    = 80    # max characters per comment (shorter = faster Qwen response)


_OLLAMA_TOPIC_PROMPT = """\
You are a social media analytics expert specializing in Arabic, Tunisian Arabizi, French, and English.
Below are ALL {total} real comments from a social media creator's posts.

Comments may be in Arabic script, Tunisian Arabizi (Latin-script Arabic dialect), French, English, or mixed.

TASK: Identify the top {top_n} recurring THEMES.

STRICT RULES:
- Group semantically similar comments into ONE theme regardless of the language they use.
  Example: "livraison?", "est ce qu'il y a la livraison", "نوزيرفيللا شافيك", "wen livraison" → ONE theme: "Delivery inquiries"
- Write each theme label in English, 2-5 words, descriptive and specific
- count = actual number of comments from these {total} that match this theme
- NEVER copy a comment verbatim as a label
- Merge near-duplicate themes into one
- Only include themes that genuinely recur — skip one-off mentions
- Return ONLY a valid JSON array, zero explanation, no markdown fences

Output format exactly:
[{{"topic": "Theme name", "count": N}}, ...]

Comments:
{numbered}
"""


_OLLAMA_BATCH_SIZE = 300   # comments per Ollama call


def _try_ollama(texts: List[str], top_n: int) -> Optional[List[Dict]]:
    """Call local Ollama in batches and merge topic counts. Returns None on total failure."""
    import httpx
    import json as _json
    import random as _random

    try:
        from app.config import settings
        ollama_url = getattr(settings, "OLLAMA_URL", "").strip().rstrip("/")
        model = getattr(settings, "OLLAMA_MODEL", "qwen2.5:7b").strip()
    except Exception:
        return None

    if not ollama_url:
        return None

    filtered = [t[:_HF_MAX_CHARS] for t in texts if t and t.strip()]
    if not filtered:
        return None

    _random.shuffle(filtered)
    batches = [
        filtered[i:i + _OLLAMA_BATCH_SIZE]
        for i in range(0, len(filtered), _OLLAMA_BATCH_SIZE)
    ]

    merged: Dict[str, tuple] = {}  # lowercase_key → (display_name, count)
    success = 0

    for i, batch in enumerate(batches):
        numbered = "\n".join(f"{j+1}. {c}" for j, c in enumerate(batch))
        prompt = _OLLAMA_TOPIC_PROMPT.format(total=len(batch), top_n=top_n, numbered=numbered)
        try:
            resp = httpx.post(
                f"{ollama_url}/api/chat",
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "stream": False,
                    "options": {"temperature": 0.1, "num_predict": 1024, "num_ctx": 16384},
                },
                timeout=180,
            )
            resp.raise_for_status()
            content = resp.json()["message"]["content"]
            data = _json.loads(content)
            raw = data if isinstance(data, list) else data.get("topics", [])
            for t in raw:
                name = (t.get("topic") or "").strip()
                count = int(t.get("count") or 1)
                if not name:
                    continue
                key = name.lower()
                if key in merged:
                    merged[key] = (merged[key][0], merged[key][1] + count)
                else:
                    merged[key] = (name, count)
            success += 1
            logger.info(
                "Ollama batch %d/%d: OK (%d comments)", i + 1, len(batches), len(batch)
            )
        except Exception as exc:
            logger.warning("Ollama batch %d/%d failed: %s", i + 1, len(batches), exc)

    if not merged:
        return None

    result = sorted(merged.values(), key=lambda x: x[1], reverse=True)
    result = [{"topic": name, "count": count} for name, count in result[:top_n]]
    logger.info(
        "Ollama topic extraction: %d themes from %d/%d batches (%d total comments)",
        len(result), success, len(batches), len(filtered),
    )
    return result


def extract_topics_with_ai(
    texts: List[str],
    top_n: int = 10,
) -> List[Dict]:
    """
    Extract semantic topic clusters.
      1. Local Ollama (Qwen2.5:7b) — semantic clustering
      2. Word-frequency            — fallback, always available
    """
    if not texts:
        return []

    try:
        from app.config import settings
        ollama_url = getattr(settings, "OLLAMA_URL", "").strip()
    except Exception:
        ollama_url = ""

    if ollama_url:
        result = _try_ollama(texts, top_n)
        if result:
            return result
        logger.warning("Ollama failed — falling back to word-frequency topic extraction")

    logger.info("Using word-frequency topic extraction")
    return extract_trending_topics(texts, top_n)
