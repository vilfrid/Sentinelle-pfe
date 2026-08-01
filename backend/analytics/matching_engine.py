"""
Enhanced Brand-Creator Matching Engine.

Composite score (6 signals, weights sum to 1.0):
  0.32 * semantic          — embedding cosine similarity (BGE-M3 vectors)
  0.20 * niche             — topic / hashtag / caption / bio keyword overlap
                             + semantic floor (max with semantic×0.35)
  0.20 * audience_quality  — engagement rate (per-post, media-aware) + authenticity
                             + comment depth + virality (share rate)
  0.13 * reach             — avg views / likes proxy (log) + followers (log) + tier bonus
  0.10 * brand_safety      — positive/negative sentiment profile
  0.05 * recency           — exponential decay from latest post (half-life = 60 days)

Niche sub-weights:    topic 40% | hashtag 20% | caption 20% | bio 20%
Audience sub-weights: engagement 45% | authenticity 25% | comment depth 10% | virality 20%
Reach sub-weights:    avg views 50% | followers 35% | tier bonus 15%

Semantic floor on niche:
  When keyword-level niche is below semantic×0.35, the semantic score itself
  provides the niche estimate. Prevents penalising creators whose audience
  topics are described in different words than campaign keywords (multilingual,
  paraphrase, or absent captions).

Topic scoring improvements:
  - Phrase-level matching: "food delivery" keyword matches "Delivery Inquiries" topic
    (AI semantic topics are multi-word; token-only matching undersells them).
  - Bio keyword matching: creator bio now reliably populated — used as 4th niche signal.

Virality signal:
  avg_shares / avg_reach proxy → log-scaled. Captures organic amplification
  which is extremely valuable for brand campaigns (each share = free impressions).
"""
import json
import logging
import math
import re
from collections import defaultdict
from datetime import datetime, timezone
from typing import List, Tuple, Optional, Dict

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.creator import Creator
from app.models.campaign import Campaign
from app.models.post import Post
from app.models.platform import Platform

logger = logging.getLogger(__name__)

# ── Thresholds ───────────────────────────────────────────────────────────────
_MIN_SCORE    = 0.04
_MIN_COMMENTS = 5    # was 10 — nano-influencers with few posts still valid

# ── Composite weights (sum = 1.0) ────────────────────────────────────────────
_W_SEMANTIC  = 0.32  # bumped: BGE-M3 multilingual now reliably available
_W_NICHE     = 0.20
_W_AUDIENCE  = 0.20
_W_REACH     = 0.13
_W_SAFETY    = 0.10
_W_RECENCY   = 0.05

# Niche semantic floor
_NICHE_SEMANTIC_FLOOR = 0.35

# ── Niche sub-weights (sum = 1.0) ────────────────────────────────────────────
_WN_TOPIC   = 0.40   # AI semantic topics (multi-word, e.g. "Delivery Inquiries")
_WN_HASHTAG = 0.20   # hashtags from posts
_WN_CAPTION = 0.20   # caption keyword density
_WN_BIO     = 0.20   # creator bio keyword match (now reliably populated)

# ── Audience sub-weights (sum = 1.0) ─────────────────────────────────────────
_WA_ENG   = 0.45   # engagement rate (per-post, media-type aware)
_WA_AUTH  = 0.25   # comment/like authenticity ratio
_WA_DEPTH = 0.10   # avg comments per post
_WA_VIRAL = 0.20   # share rate — organic amplification

# ── Reach sub-weights (sum = 1.0) ────────────────────────────────────────────
_WR_VIEWS     = 0.50
_WR_FOLLOWERS = 0.35
_WR_TIER      = 0.15

# ── Platform engagement benchmarks (industry 2024-2025 averages) ─────────────
_PLATFORM_ENG = {
    "instagram": 0.028,   # avg ~2.8% across creators
    "youtube":   0.012,   # avg ~1.2% (views >> likes for long-form)
}
_DEFAULT_ENG = 0.030

# ── Influencer tiers ─────────────────────────────────────────────────────────
_TIERS = [
    (1_000_000, "mega",  0.75),
    (100_000,   "macro", 0.90),
    (10_000,    "micro", 1.00),
    (1,         "nano",  0.70),
    (0,         "unknown", 0.50),
]

# ── Normalization references ──────────────────────────────────────────────────
_MAX_VIEW_LOG     = math.log1p(50_000_000)
_MAX_FOLLOWER_LOG = math.log1p(10_000_000)
_RECENCY_HALF_LIFE_DAYS = 60

# ── Cache ─────────────────────────────────────────────────────────────────────
_CACHE_KEY = "matching:campaign:{}"
_CACHE_TTL = 86400  # 24 h

# ── Misc ──────────────────────────────────────────────────────────────────────
_STOP_WORDS = {
    "and", "or", "the", "a", "an", "of", "in", "for", "to", "is", "are",
    "with", "on", "at", "by", "from", "as", "its", "this", "that",
}
_HASHTAG_RE = re.compile(r"#(\w+)")


# ── Low-level helpers ─────────────────────────────────────────────────────────

def _extract_hashtags(caption: str) -> List[str]:
    return [t.lower() for t in _HASHTAG_RE.findall(caption or "")]


def _cosine(v1: List[float], v2: List[float]) -> float:
    import numpy as np
    a, b = np.array(v1, dtype=np.float32), np.array(v2, dtype=np.float32)
    na, nb = np.linalg.norm(a), np.linalg.norm(b)
    if na == 0 or nb == 0:
        return 0.0
    return float(max(np.dot(a, b) / (na * nb), 0.0))


def _keyword_jaccard(brand_kw: List[str], creator_topics: List[str]) -> float:
    if not brand_kw or not creator_topics:
        return 0.0
    a = {k.lower() for k in brand_kw}
    b = {str(t).lower() for t in creator_topics}
    return len(a & b) / max(len(a | b), 1)


def _influencer_tier(follower_count: int) -> Tuple[str, float]:
    for threshold, label, bonus in _TIERS:
        if follower_count >= threshold:
            return label, bonus
    return "unknown", 0.5


# ── Post-level stats ──────────────────────────────────────────────────────────

def _compute_post_stats(posts: List[Post], creator_total_comments: int = 0) -> Dict:
    """
    Per-post, media-type-aware engagement:
      - video posts (media_type=2): (likes+comments+shares×3) / views
      - photo/other posts:          (comments+shares×3) / likes
    This prevents creators with mixed content from being penalised when
    photos have 0 views but healthy like counts.
    """
    if not posts:
        return {
            "avg_views": 0, "avg_likes": 0, "avg_comments": 0, "avg_shares": 0,
            "engagement_rate": 0.0, "total_views": 0, "total_likes": 0,
            "hashtags": [], "post_count": 0, "authenticity": 0.5,
            "latest_post_date": None, "share_rate": 0.0,
            "content_type_mix": {"video": 0, "photo": 0, "carousel": 0},
        }
    n = len(posts)
    total_views    = sum(p.views or 0 for p in posts)
    total_likes    = sum(p.likes or 0 for p in posts)
    total_comments = sum(p.comment_count or 0 for p in posts)
    total_shares   = sum(p.shares or 0 for p in posts)
    avg_views    = total_views / n
    avg_likes    = total_likes / n
    avg_shares   = total_shares / n
    if total_comments == 0 and creator_total_comments > 0:
        total_comments = creator_total_comments
    avg_comments = total_comments / n

    # Per-post engagement (media-type aware)
    post_eng_rates = []
    for p in posts:
        v = p.views or 0
        l = p.likes or 0
        c = p.comment_count or 0
        s = p.shares or 0
        if v > 0:
            post_eng_rates.append(min((l + c + s * 3) / v, 1.0))
        elif l > 0:
            post_eng_rates.append(min((c + s * 3) / l, 0.20))
    eng_rate = sum(post_eng_rates) / n if post_eng_rates else 0.0

    # Authenticity: comment-to-like ratio proxy
    if avg_likes > 0:
        ratio = avg_comments / avg_likes
        if ratio < 0.0003:
            auth = 0.20
        elif ratio < 0.002:
            auth = 0.65
        elif ratio < 0.01:
            auth = 0.85
        elif ratio < 0.05:
            auth = 1.00
        elif ratio < 0.20:
            auth = 0.80
        else:
            auth = 0.55
    elif avg_comments > 0:
        auth = 0.70
    else:
        auth = 0.50

    # Deduplicated hashtags
    seen: set = set()
    hashtags: List[str] = []
    for p in posts:
        raw_tags = []
        if p.tags:
            try:
                raw_tags = json.loads(p.tags)
            except Exception:
                raw_tags = _extract_hashtags(p.caption or "")
        else:
            raw_tags = _extract_hashtags(p.caption or "")
        for h in raw_tags:
            if h not in seen:
                seen.add(h)
                hashtags.append(h)

    # Latest post date for recency
    latest = None
    for p in posts:
        if p.posted_at and (latest is None or p.posted_at > latest):
            latest = p.posted_at

    # Content type mix (media_type: 1=photo, 2=video/reel, 8=carousel)
    video_n    = sum(1 for p in posts if (p.media_type or 1) == 2)
    photo_n    = sum(1 for p in posts if (p.media_type or 1) == 1)
    carousel_n = sum(1 for p in posts if (p.media_type or 1) == 8)
    content_type_mix = {
        "video":    round(video_n / n * 100),
        "photo":    round(photo_n / n * 100),
        "carousel": round(carousel_n / n * 100),
    }

    # Share rate: shares relative to reach proxy
    share_rate = avg_shares / max(avg_views, avg_likes * 10, 1)

    return {
        "avg_views":        avg_views,
        "avg_likes":        avg_likes,
        "avg_comments":     avg_comments,
        "avg_shares":       avg_shares,
        "engagement_rate":  eng_rate,
        "total_views":      total_views,
        "total_likes":      total_likes,
        "hashtags":         hashtags,
        "post_count":       n,
        "authenticity":     auth,
        "latest_post_date": latest,
        "share_rate":       share_rate,
        "content_type_mix": content_type_mix,
    }


# ── Scoring functions ─────────────────────────────────────────────────────────

def _topic_score(campaign_keywords: List[str], creator_topics: List[str]) -> float:
    """
    Two-pass matching for AI-extracted multi-word topics:
      1. Token-level: word set intersection (handles synonyms / multilingual)
      2. Phrase-level: does any topic phrase contain a campaign keyword or vice-versa?
         e.g. keyword "delivery" matches topic "Delivery Inquiries"
    """
    if not campaign_keywords or not creator_topics:
        return 0.0
    kw_tokens = {w.lower() for kw in campaign_keywords for w in kw.split()} - _STOP_WORDS
    tp_tokens  = {w.lower() for t in creator_topics for w in t.split()} - _STOP_WORDS
    if not kw_tokens or not tp_tokens:
        return 0.0

    token_score = len(kw_tokens & tp_tokens) / math.sqrt(len(kw_tokens) * len(tp_tokens))

    # Phrase containment (one direction or the other)
    tp_lower = [t.lower() for t in creator_topics]
    kw_lower = [kw.lower() for kw in campaign_keywords]
    phrase_hits = sum(
        1 for kw in kw_lower for t in tp_lower
        if kw in t or t in kw
    )
    phrase_score = min(phrase_hits / max(len(kw_lower), 1), 1.0) * 0.8

    return max(token_score, phrase_score)


def _hashtag_score(campaign_keywords: List[str], post_hashtags: List[str]) -> float:
    if not campaign_keywords or not post_hashtags:
        return 0.0
    kw = {w.lower() for kw in campaign_keywords for w in kw.split()} - _STOP_WORDS
    ht = {h.lower() for h in post_hashtags}
    if not kw or not ht:
        return 0.0
    overlap = len(kw & ht)
    return overlap / math.sqrt(len(kw) * len(ht))


def _caption_keyword_density(campaign_keywords: List[str], posts: List[Post]) -> float:
    """Fraction of posts that contain at least one campaign keyword in their caption."""
    if not campaign_keywords or not posts:
        return 0.0
    tokens = {w.lower() for kw in campaign_keywords for w in kw.split()} - _STOP_WORDS
    if not tokens:
        return 0.0
    hits = sum(
        1 for p in posts
        if p.caption and any(tok in p.caption.lower() for tok in tokens)
    )
    return hits / len(posts)


def _bio_score(campaign_keywords: List[str], bio: str) -> float:
    """Campaign keyword overlap with creator bio text.
    Bio is now reliably populated for Instagram, TikTok, and YouTube creators.
    """
    if not campaign_keywords or not bio:
        return 0.0
    tokens = {w.lower() for kw in campaign_keywords for w in kw.split()} - _STOP_WORDS
    # Match Arabic and Latin words (≥3 chars each)
    bio_words = {w.lower() for w in re.findall(r"[؀-ۿa-zA-Z]{3,}", bio)}
    if not tokens or not bio_words:
        return 0.0
    overlap = len(tokens & bio_words)
    return min(overlap / math.sqrt(max(len(tokens), 1)), 1.0)


def _virality_score(post_stats: Dict) -> float:
    """Organic amplification via shares.
    share_rate = avg_shares / reach_proxy → log-scaled to [0, 1].
    High share rate signals content that audiences actively spread,
    which multiplies brand reach beyond the follower base.
    """
    avg_shares = post_stats.get("avg_shares", 0)
    avg_views  = post_stats.get("avg_views", 0)
    avg_likes  = post_stats.get("avg_likes", 0)
    denominator = max(avg_views, avg_likes * 10, 1)
    share_rate = avg_shares / denominator
    return min(math.log1p(share_rate * 500) / math.log1p(500), 1.0)


def _niche_score(
    brand_keywords: List[str],
    creator_topics: List[str],
    post_stats: Dict,
    posts: List[Post],
    semantic_score: float = 0.0,
    creator_bio: str = "",
) -> Tuple[float, float, float, float, float]:
    """Returns (composite, topic_s, hashtag_s, caption_s, bio_s).

    Applies a semantic floor so creators with strong embedding alignment
    never get niche=0 due to missing caption/hashtag data or multilingual topics.
    """
    ts = _topic_score(brand_keywords, creator_topics)
    hs = _hashtag_score(brand_keywords, post_stats["hashtags"])
    cs = _caption_keyword_density(brand_keywords, posts)
    bs = _bio_score(brand_keywords, creator_bio)
    keyword_composite = _WN_TOPIC * ts + _WN_HASHTAG * hs + _WN_CAPTION * cs + _WN_BIO * bs
    semantic_floor = semantic_score * _NICHE_SEMANTIC_FLOOR
    composite = max(keyword_composite, semantic_floor)
    return composite, ts, hs, cs, bs


def _audience_score(post_stats: Dict, platform_name: str) -> Tuple[float, float, float, float, float]:
    """Returns (composite, eng_score, authenticity, depth_score, virality_score)."""
    baseline = _PLATFORM_ENG.get(platform_name, _DEFAULT_ENG)
    eng_rate = post_stats["engagement_rate"]

    if baseline > 0 and eng_rate > 0:
        eng_score = min(math.log1p(eng_rate / baseline * 10) / math.log1p(10), 1.0)
    else:
        eng_score = 0.0

    authenticity = post_stats["authenticity"]

    avg_comments = post_stats.get("avg_comments", 0)
    depth = min(math.log1p(avg_comments) / math.log1p(200), 1.0)

    viral_s = _virality_score(post_stats)

    composite = (
        _WA_ENG   * eng_score
        + _WA_AUTH  * authenticity
        + _WA_DEPTH * depth
        + _WA_VIRAL * viral_s
    )
    return composite, eng_score, authenticity, depth, viral_s


def _reach_score(creator: Creator, post_stats: Dict, tier_bonus: float) -> Tuple[float, float, float]:
    """Returns (composite, view_score, follower_score).

    When avg_views is 0 (Instagram image posts, TikTok with missing data),
    fall back to avg_likes or avg_shares as reach proxy.
    """
    avg_views  = post_stats["avg_views"]
    avg_likes  = post_stats["avg_likes"]
    avg_shares = post_stats.get("avg_shares", 0)
    followers  = creator.follower_count or 0

    effective_views = avg_views if avg_views > 0 else max(avg_shares * 50, avg_likes * 10)
    view_score     = min(math.log1p(effective_views) / _MAX_VIEW_LOG, 1.0) if effective_views > 0 else 0.0
    follower_score = min(math.log1p(followers) / _MAX_FOLLOWER_LOG, 1.0) if followers > 0 else 0.0
    composite = _WR_VIEWS * view_score + _WR_FOLLOWERS * follower_score + _WR_TIER * tier_bonus
    return composite, view_score, follower_score


def _brand_safety_score(creator: Creator) -> float:
    pos = (creator.positive_pct or 0.0) / 100.0
    neg = (creator.negative_pct or 0.0) / 100.0
    safety = pos * (1.0 - math.sqrt(neg))
    return max(0.0, min(safety, 1.0))


def _recency_score(post_stats: Dict) -> float:
    """Exponential decay from latest post. 1.0 = today, ~0.5 = 60 days ago."""
    latest = post_stats.get("latest_post_date")
    if not latest:
        return 0.50
    if latest.tzinfo is None:
        latest = latest.replace(tzinfo=timezone.utc)
    days = max((datetime.now(timezone.utc) - latest).days, 0)
    return math.exp(-math.log(2) * days / _RECENCY_HALF_LIFE_DAYS)


def _estimated_reach(creator: Creator, post_stats: Dict) -> int:
    """Best estimate of unique eyeballs per post."""
    avg_views  = int(post_stats.get("avg_views", 0))
    followers  = creator.follower_count or 0
    avg_likes  = int(post_stats.get("avg_likes", 0))
    avg_shares = int(post_stats.get("avg_shares", 0))
    return max(avg_views, avg_shares * 20, followers, avg_likes * 10)


# ── Main Engine ───────────────────────────────────────────────────────────────

class MatchingEngine:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def match(self, campaign_id: int, top_k: int = 10) -> List[dict]:
        campaign = await self.db.get(Campaign, campaign_id)
        if not campaign:
            return []

        platforms = (await self.db.scalars(select(Platform))).all()
        platform_names: Dict[int, str] = {p.id: p.name.lower() for p in platforms}

        creators = (await self.db.scalars(select(Creator))).all()
        if not creators:
            return []

        eligible_ids = [c.id for c in creators if (c.total_comments or 0) >= _MIN_COMMENTS]
        all_posts: List[Post] = []
        if eligible_ids:
            all_posts = (await self.db.scalars(
                select(Post).where(Post.creator_id.in_(eligible_ids))
            )).all()

        creator_posts: Dict[int, List[Post]] = defaultdict(list)
        for post in all_posts:
            creator_posts[post.creator_id].append(post)

        campaign_embedding = self._load_embedding(campaign)
        brand_keywords = list(campaign.keywords or [])
        # Pull content words from campaign description into keyword pool
        if campaign.description:
            desc_words = [
                w for w in re.sub(r"[^\w\s]", " ", campaign.description).split()
                if len(w) >= 4 and w.lower() not in _STOP_WORDS
            ]
            existing = {k.lower() for k in brand_keywords}
            brand_keywords += [w for w in desc_words if w.lower() not in existing]

        scored: List[Tuple] = []

        for creator in creators:
            if (creator.total_comments or 0) < _MIN_COMMENTS:
                continue

            posts          = creator_posts[creator.id]
            post_stats     = _compute_post_stats(posts, creator.total_comments or 0)
            platform_name  = platform_names.get(creator.platform_id, "instagram")
            topic_names    = self._extract_topic_names(creator.top_topics)
            tier, tier_b   = _influencer_tier(creator.follower_count or 0)

            # ── 1. Semantic ──────────────────────────────────────────────────
            creator_embedding = self._load_creator_embedding(creator)
            if campaign_embedding and creator_embedding:
                semantic = _cosine(campaign_embedding, creator_embedding)
                method   = "embedding"
            else:
                semantic = _keyword_jaccard(brand_keywords, topic_names)
                method   = "keyword"

            # ── 2. Niche (topic + hashtag + caption + bio) ───────────────────
            niche, topic_s, hashtag_s, caption_s, bio_s = _niche_score(
                brand_keywords, topic_names, post_stats, posts,
                semantic_score=semantic,
                creator_bio=creator.bio or "",
            )

            # ── 3. Audience Quality ──────────────────────────────────────────
            audience, eng_s, auth_s, depth_s, viral_s = _audience_score(post_stats, platform_name)

            # ── 4. Reach ─────────────────────────────────────────────────────
            reach, view_s, follower_s = _reach_score(creator, post_stats, tier_b)

            # ── 5. Brand Safety ──────────────────────────────────────────────
            safety = _brand_safety_score(creator)

            # ── 6. Recency ────────────────────────────────────────────────────
            recency = _recency_score(post_stats)

            # ── Composite ────────────────────────────────────────────────────
            composite = (
                _W_SEMANTIC  * semantic
                + _W_NICHE   * niche
                + _W_AUDIENCE * audience
                + _W_REACH   * reach
                + _W_SAFETY  * safety
                + _W_RECENCY * recency
            )

            if composite < _MIN_SCORE:
                continue

            brand_set     = {k.lower() for k in brand_keywords}
            shared_topics = list(brand_set & {t.lower() for t in topic_names})
            shared_tags   = list(brand_set & {h.lower() for h in post_stats["hashtags"]})
            est_reach     = _estimated_reach(creator, post_stats)

            scored.append((
                composite, semantic, niche, audience, reach, safety, recency,
                topic_s, hashtag_s, caption_s, bio_s, eng_s, auth_s, depth_s, viral_s,
                view_s, follower_s, tier_b,
                creator, method, shared_topics, shared_tags, post_stats,
                tier, platform_name, est_reach,
            ))

        scored.sort(key=lambda x: x[0], reverse=True)

        results = []
        for row in scored[:top_k]:
            (composite, semantic, niche, audience, reach, safety, recency,
             topic_s, hashtag_s, caption_s, bio_s, eng_s, auth_s, depth_s, viral_s,
             view_s, follower_s, tier_b,
             creator, method, shared_topics, shared_tags, post_stats,
             tier, platform_name, est_reach) = row

            topic_names = self._extract_topic_names(creator.top_topics)

            results.append({
                "creator": {
                    "id": creator.id,
                    "username": creator.username,
                    "display_name": creator.display_name,
                    "bio": creator.bio,
                    "profile_url": creator.profile_url,
                    "avatar_url": creator.avatar_url,
                    "follower_count": creator.follower_count or 0,
                    "total_comments": creator.total_comments or 0,
                    "positive_pct": creator.positive_pct or 0.0,
                    "negative_pct": creator.negative_pct or 0.0,
                    "neutral_pct": creator.neutral_pct or 0.0,
                    "audience_mood": creator.audience_mood,
                    "content_topics": topic_names,
                    "has_embedding": creator.content_embedding is not None,
                    "campaign_id": creator.campaign_id,
                    "influencer_tier": tier,
                    "platform": platform_name,
                    "post_count": post_stats["post_count"],
                    "avg_views": round(post_stats["avg_views"]),
                    "avg_likes": round(post_stats["avg_likes"]),
                    "avg_shares": round(post_stats["avg_shares"]),
                    "avg_comments_per_post": round(post_stats["avg_comments"]),
                    "engagement_rate": round(post_stats["engagement_rate"] * 100, 2),
                    "share_rate": round(post_stats.get("share_rate", 0) * 100, 4),
                    "top_hashtags": post_stats["hashtags"][:10],
                    "authenticity_score": round(auth_s, 3),
                    "estimated_reach": est_reach,
                    "content_type_mix": post_stats.get("content_type_mix", {}),
                },
                "match_score": round(composite, 4),
                "score_breakdown": {
                    "semantic":          round(semantic, 4),
                    "niche":             round(niche, 4),
                    "audience":          round(audience, 4),
                    "reach":             round(reach, 4),
                    "brand_safety":      round(safety, 4),
                    "recency":           round(recency, 4),
                    "topic_overlap":     round(topic_s, 4),
                    "hashtag_overlap":   round(hashtag_s, 4),
                    "caption_density":   round(caption_s, 4),
                    "bio_match":         round(bio_s, 4),
                    "engagement_score":  round(eng_s, 4),
                    "authenticity":      round(auth_s, 4),
                    "comment_depth":     round(depth_s, 4),
                    "virality":          round(viral_s, 4),
                    "niche_from_semantic": niche > (_WN_TOPIC * topic_s + _WN_HASHTAG * hashtag_s + _WN_CAPTION * caption_s + _WN_BIO * bio_s),
                },
                "method": method,
                "matching_topics": shared_topics,
                "matching_hashtags": shared_tags,
                "estimated_reach": est_reach,
                "influencer_tier": tier,
                "platform": platform_name,
                "reasoning": _build_reasoning(
                    composite, semantic, niche, audience, reach, safety,
                    topic_s, hashtag_s, caption_s, bio_s, eng_s, auth_s, viral_s,
                    method, shared_topics, shared_tags,
                    creator, post_stats, tier,
                ),
            })

        return results

    def _load_embedding(self, campaign: Campaign) -> Optional[List[float]]:
        raw = getattr(campaign, "campaign_embedding", None)
        if not raw:
            return None
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return None

    def _load_creator_embedding(self, creator: Creator) -> Optional[List[float]]:
        if not creator.content_embedding:
            return None
        try:
            return json.loads(creator.content_embedding)
        except (json.JSONDecodeError, TypeError):
            return None

    def _extract_topic_names(self, top_topics) -> List[str]:
        if not top_topics:
            return []
        names = []
        for t in top_topics:
            if isinstance(t, dict):
                names.append(str(t.get("topic", "")))
            elif isinstance(t, str):
                names.append(t)
        return [n for n in names if n]


# ── Reasoning builder ─────────────────────────────────────────────────────────

def _build_reasoning(
    composite: float,
    semantic: float,
    niche: float,
    audience: float,
    reach: float,
    safety: float,
    topic_s: float,
    hashtag_s: float,
    caption_s: float,
    bio_s: float,
    eng_s: float,
    auth_s: float,
    viral_s: float,
    method: str,
    shared_topics: List[str],
    shared_tags: List[str],
    creator: Creator,
    post_stats: Dict,
    tier: str,
) -> str:
    parts = []

    # Semantic / keyword
    if method == "embedding":
        parts.append(f"Semantic similarity: {semantic:.1%}")
    else:
        parts.append(f"Keyword match: {semantic:.1%}")

    # Niche signals
    if niche > 0.02:
        if topic_s > 0:
            parts.append(f"Topic match: {topic_s:.1%}")
        if hashtag_s > 0:
            parts.append(f"Hashtag match: {hashtag_s:.1%}")
        if caption_s > 0.10:
            parts.append(f"Keywords in {caption_s:.0%} of posts")
        if bio_s > 0.10:
            parts.append(f"Bio match: {bio_s:.1%}")

    # Audience
    pos = creator.positive_pct or 0
    neg = creator.negative_pct or 0
    if pos >= 60:
        parts.append(f"Positive audience ({pos:.0f}% pos)")
    elif neg >= 20:
        parts.append(f"High negativity warning ({neg:.0f}%)")
    if auth_s >= 0.85:
        parts.append("Authentic engagement")
    elif auth_s < 0.35:
        parts.append("Low engagement authenticity")

    # Virality
    avg_shares = post_stats.get("avg_shares", 0)
    if avg_shares >= 10_000:
        parts.append(f"{avg_shares / 1_000:.0f}K avg reposts")
    elif avg_shares >= 1_000:
        parts.append(f"{avg_shares / 1_000:.1f}K avg reposts")
    elif avg_shares >= 100:
        parts.append(f"{int(avg_shares)} avg reposts")
    elif viral_s >= 0.50:
        parts.append("High share rate")

    # Reach
    avg_views = post_stats.get("avg_views", 0)
    if avg_views >= 1_000_000:
        parts.append(f"{avg_views / 1_000_000:.1f}M avg views")
    elif avg_views >= 1_000:
        parts.append(f"{avg_views / 1_000:.0f}K avg views")
    eng = post_stats.get("engagement_rate", 0)
    if eng > 0.04:
        parts.append(f"{eng * 100:.1f}% engagement")
    followers = creator.follower_count or 0
    if followers >= 1_000_000:
        parts.append(f"{followers / 1_000_000:.1f}M followers")
    elif followers >= 1_000:
        parts.append(f"{followers / 1_000:.0f}K followers")

    # Content mix note
    mix = post_stats.get("content_type_mix", {})
    if mix.get("video", 0) >= 70:
        parts.append("Mostly video/reels")
    elif mix.get("photo", 0) >= 70:
        parts.append("Mostly photos")

    # Tier
    parts.append(f"{tier.capitalize()} influencer")

    # Matching keywords
    if shared_topics:
        parts.append(f"Topics: {', '.join(shared_topics[:3])}")
    if shared_tags:
        parts.append(f"Tags: {' '.join('#' + t for t in shared_tags[:3])}")

    return " · ".join(parts)


# ── Cache refresh helper ──────────────────────────────────────────────────────

async def compute_and_cache_all(redis_client) -> int:
    """Recompute matching for every campaign and store in Redis."""
    from app.database import AsyncSessionLocal
    refreshed = 0
    try:
        async with AsyncSessionLocal() as db:
            campaigns = (await db.scalars(select(Campaign))).all()
            engine = MatchingEngine(db)
            for campaign in campaigns:
                try:
                    results = await engine.match(campaign.id, top_k=20)
                    key = _CACHE_KEY.format(campaign.id)
                    redis_client.setex(key, _CACHE_TTL, json.dumps(results))
                    refreshed += 1
                except Exception as exc:
                    logger.warning("Auto-match cache failed for campaign %d: %s", campaign.id, exc)
    except Exception as exc:
        logger.warning("compute_and_cache_all failed: %s", exc)
    return refreshed
