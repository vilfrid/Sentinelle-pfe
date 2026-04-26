"""
Trending topics extraction using simple TF-IDF on Arabic/Arabizi comments.
"""
import re
import logging
from collections import Counter
from typing import List, Dict

logger = logging.getLogger(__name__)

_STOPWORDS_AR = {
    "في", "من", "على", "إلى", "عن", "مع", "هذا", "هذه", "التي", "الذي",
    "كان", "كانت", "يكون", "تكون", "وأن", "أنا", "أنت", "هو", "هي",
    "نحن", "هم", "هل", "لا", "ما", "لم", "لن", "قد", "إن", "أن",
    "و", "أو", "ثم", "لكن", "بل", "حتى",
}

_STOPWORDS_MISC = {
    "the", "a", "an", "is", "are", "was", "were", "و",
    "de", "le", "la", "les", "je", "tu", "il",
}

_ALL_STOPS = _STOPWORDS_AR | _STOPWORDS_MISC
_MIN_WORD_LEN = 3


def extract_trending_topics(texts: List[str], top_n: int = 20) -> List[Dict]:
    word_counts: Counter = Counter()
    for text in texts:
        words = re.findall(r"[؀-ۿa-zA-Z]{3,}", text)
        for word in words:
            w = word.strip()
            if len(w) >= _MIN_WORD_LEN and w.lower() not in _ALL_STOPS:
                word_counts[w] += 1

    return [
        {"topic": word, "count": count}
        for word, count in word_counts.most_common(top_n)
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
