"""
Trending topics extraction for Arabic/Arabizi/French/English social media comments.

Two extraction modes:
  extract_topics_with_ai()   — Gemini 2.0 Flash: semantic theme clustering (primary)
  extract_trending_topics()  — word-frequency fallback (used when AI is unavailable)
"""
import json
import random
import re
import logging
from collections import Counter
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)

_AI_SAMPLE_SIZE = 150   # max comments sent to Gemini per call
_AI_MODEL = "gemini-2.0-flash"
_AI_RETRIES = 2

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
_MIN_COUNT = 2  # ignore hapax legomena (words appearing only once)

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

    return [
        {"topic": word, "count": count}
        for word, count in word_counts.most_common(top_n)
        if count >= _MIN_COUNT
    ]


def extract_hashtags(texts: List[str]) -> List[Dict]:
    tag_counts: Counter = Counter()
    for text in texts:
        for tag in re.findall(r"#\w+", text):
            tag_counts[tag.lower()] += 1
    return [
        {"hashtag": tag, "count": count}
        for tag, count in tag_counts.most_common(15)
    ]


def extract_topics_with_ai(
    texts: List[str],
    top_n: int = 10,
    api_key: Optional[str] = None,
) -> List[Dict]:
    """
    Use Gemini to extract semantic topic clusters from comment texts.
    Returns the same [{"topic": str, "count": int}] shape as extract_trending_topics().
    Falls back to word-frequency extraction on any failure.

    `count` represents Gemini's estimated number of comments touching each theme.
    """
    if not texts:
        return []

    # lazy import — tasks.py runs in Celery workers where google.generativeai may not
    # be imported at module load time
    try:
        import google.generativeai as genai
    except ImportError:
        logger.warning("google-generativeai not installed — falling back to word frequency")
        return extract_trending_topics(texts, top_n)

    key = api_key
    if not key:
        try:
            from app.config import settings
            key = settings.GOOGLE_API_KEY
        except Exception:
            pass

    if not key:
        logger.warning("GOOGLE_API_KEY not available — falling back to word frequency")
        return extract_trending_topics(texts, top_n)

    genai.configure(api_key=key)
    model = genai.GenerativeModel(_AI_MODEL)

    # Sample comments — random sample when corpus is large
    sample = texts if len(texts) <= _AI_SAMPLE_SIZE else random.sample(texts, _AI_SAMPLE_SIZE)
    total = len(texts)

    numbered = "\n".join(f"{i+1}. {t[:200]}" for i, t in enumerate(sample))

    prompt = f"""You are a social media analytics expert analyzing comments from a brand campaign.
The comments may be in Arabic, French, Tunisian Arabizi (Franco-Arabic dialect), or English — analyze all of them together.

Your task: identify the top {top_n} recurring THEMES or TOPICS that commenters are talking about.
Focus on meaningful subjects (product features, price, emotions, events, people mentioned, complaints, compliments).
Ignore generic filler words, greetings, and platform noise.

IMPORTANT:
- Write each topic label in English (2–5 words max, e.g. "Product quality", "Price concerns", "Delivery issues")
- Estimate how many of the {total} total comments touch on each theme (integer)
- Return ONLY valid JSON, no markdown, no explanation

Sample ({len(sample)} of {total} comments):
{numbered}

Respond with exactly this JSON structure:
{{"topics": [{{"topic": "Theme label", "count": N}}, ...]}}"""

    for attempt in range(_AI_RETRIES):
        try:
            response = model.generate_content(prompt)
            clean = re.sub(r"```(?:json)?\s*|\s*```", "", response.text).strip()
            parsed = json.loads(clean)
            topics = parsed.get("topics", [])
            if not isinstance(topics, list) or not topics:
                raise ValueError("empty topics list")
            result = [
                {"topic": str(t["topic"]), "count": int(t["count"])}
                for t in topics
                if isinstance(t, dict) and "topic" in t and "count" in t
            ]
            if result:
                logger.info("AI topic extraction: %d themes from %d comments", len(result), total)
                return result[:top_n]
        except Exception as exc:
            logger.warning("AI topic extraction attempt %d/%d failed: %s", attempt + 1, _AI_RETRIES, exc)

    logger.warning("AI topic extraction failed — falling back to word frequency")
    return extract_trending_topics(texts, top_n)
