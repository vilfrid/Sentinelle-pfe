
import json
import logging
import re
from typing import Optional, Dict, Any, List

from groq import Groq
from app.config import settings

logger = logging.getLogger(__name__)

_MODEL = "llama-3.3-70b-versatile"
_RETRY_ATTEMPTS = 2
_REQUIRED_KEYS = {
    "summary", "sentiment_insights", "what_worked",
    "what_to_improve", "recommendations", "risk_alerts", "audience_insights",
    "trending_now", "fading_content", "content_strategy",
}


class ReportGenerator:
    def __init__(self):
        key = settings.GROQ_API_KEY or ""
        self.client = Groq(api_key=key) if key else None

    def generate(
        self,
        campaign_name: str,
        brand: str,
        metrics: Dict[str, Any],
        trending_topics: List[Dict],
        sample_comments: List[Dict],
        creator_summaries: List[Dict],
        post_analytics: Optional[Dict[str, Any]] = None,
        hashtag_trends: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        prompt = self._build_prompt(
            campaign_name, brand, metrics, trending_topics,
            sample_comments, creator_summaries,
            post_analytics or {}, hashtag_trends or {},
        )

        if not self.client:
            logger.error("GROQ_API_KEY not configured — cannot generate report")
            raise RuntimeError("GROQ_API_KEY is not configured — report generation requires the Groq API")

        for attempt in range(_RETRY_ATTEMPTS):
            try:
                response = self.client.chat.completions.create(
                    model=_MODEL,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.3,
                    max_tokens=4096,
                )
                raw = response.choices[0].message.content or ""
                parsed = self._parse_response(raw)
                if parsed:
                    logger.info("Report generated for '%s' via Groq %s", campaign_name, _MODEL)
                    return parsed
            except Exception as exc:
                err = str(exc)
                if "429" in err or "rate" in err.lower():
                    import time
                    wait = 15 * (attempt + 1)
                    logger.warning("Report generation rate-limited — waiting %ds: %s", wait, err)
                    time.sleep(wait)
                else:
                    logger.warning("Report generation attempt %d failed: %s", attempt + 1, exc)

        logger.error("Groq report generation failed after %d attempts", _RETRY_ATTEMPTS)
        raise RuntimeError("Groq API report generation failed — please retry later")

    def _build_prompt(
        self,
        campaign_name: str,
        brand: str,
        metrics: Dict[str, Any],
        trending_topics: List[Dict],
        sample_comments: List[Dict],
        creator_summaries: List[Dict],
        post_analytics: Dict[str, Any],
        hashtag_trends: Dict[str, Any],
    ) -> str:
        # ── Sentiment topics ──
        topics_str = ", ".join(
            [t.get("topic", "") for t in (trending_topics or [])]
        ) or "No trending topics detected"

        # ── Comment samples ──
        positive_comments = [c for c in sample_comments if c.get("sentiment") == "positive"][:25]
        negative_comments = [c for c in sample_comments if c.get("sentiment") == "negative"][:25]

        def fmt_comments(lst: List[Dict]) -> str:
            if not lst:
                return "  (none)\n"
            return "".join(f'  - "{c.get("text", "")}"\n' for c in lst)

        # ── Creator ranking ──
        sorted_creators = sorted(
            creator_summaries or [],
            key=lambda c: c.get("total_comments", 0),
            reverse=True,
        )
        creators_str = ""
        for i, cr in enumerate(sorted_creators, 1):
            pos  = cr.get("positive_pct", 0)
            neg  = cr.get("negative_pct", 0)
            mood = cr.get("mood", "?")
            total = cr.get("total_comments", 0)
            avg_views = cr.get("avg_views", 0)
            eng = cr.get("engagement_rate", 0)
            tags = ", ".join(f"#{t}" for t in (cr.get("top_hashtags") or [])[:5])
            creators_str += (
                f"  #{i} @{cr.get('username', '?')}: "
                f"{total} comments · {pos:.0f}% pos · {neg:.0f}% neg · mood: {mood}"
            )
            if avg_views:
                creators_str += f" · avg {_fmt_num(avg_views)} views"
            if eng:
                creators_str += f" · {eng:.1f}% engagement"
            if tags:
                creators_str += f" · tags: {tags}"
            creators_str += "\n"
        if not creators_str:
            creators_str = "  No creator data available.\n"

        # ── Post performance ──
        top_posts = post_analytics.get("top_posts_by_views", [])
        posts_str = ""
        if top_posts:
            for p in top_posts:
                views  = _fmt_num(p.get("views", 0))
                likes  = _fmt_num(p.get("likes", 0))
                shares = _fmt_num(p.get("shares", 0))
                tags   = " ".join(f"#{t}" for t in (p.get("hashtags") or []))
                caption_preview = p.get("caption_preview") or ""
                tag_part     = (" | " + tags) if tags else ""
                caption_part = (' | "' + caption_preview + '"') if caption_preview else ""
                posts_str += (
                    f"  • {views} views · {likes} likes · {shares} shares"
                    f"{tag_part}{caption_part}\n"
                )
        else:
            posts_str = "  No post view data available.\n"

        # ── Hashtag trends ──
        trending_tags  = hashtag_trends.get("trending_now", [])
        fading_tags    = hashtag_trends.get("fading", [])
        stable_tags    = hashtag_trends.get("stable", [])
        all_top_tags   = hashtag_trends.get("top_all_time", [])

        def _tag_line(tags: list) -> str:
            if not tags:
                return "  (none)\n"
            parts = []
            for t in tags:
                tag = t.get("tag", "")
                r = t.get("recent_uses", 0)
                o = t.get("old_uses", 0)
                if o:
                    parts.append(f"{tag} ({r} recent vs {o} before)")
                else:
                    parts.append(f"{tag} ({r} uses)")
            return "  " + " · ".join(parts) + "\n"

        # ── Engagement display ──
        eng = metrics.get("engagement_rate", 0)
        eng_str = f"{eng * 100:.2f}%" if eng > 0 else "N/A (no view data)"
        total_views = metrics.get("total_views", 0)
        total_likes = metrics.get("total_likes", 0)

        return f"""You are a senior social media analytics consultant specializing in the Tunisian and North-African digital market.
Analyze the data below and generate a comprehensive campaign performance report.

═══ CAMPAIGN ═══
Name: "{campaign_name}"
Brand: {brand}

═══ KEY METRICS ═══
• Total comments analyzed: {metrics.get('total_comments', 0)}
• Posts tracked: {metrics.get('total_posts', 0)}
• Total views across all posts: {_fmt_num(total_views)}
• Total likes across all posts: {_fmt_num(total_likes)}
• Total shares: {_fmt_num(metrics.get('total_shares', 0))}
• Avg views per post: {_fmt_num(metrics.get('avg_views_per_post', 0))}
• Avg likes per post: {_fmt_num(metrics.get('avg_likes_per_post', 0))}
• Positive sentiment: {metrics.get('positive_pct', 0)}%
• Negative sentiment: {metrics.get('negative_pct', 0)}%
• Neutral sentiment: {metrics.get('neutral_pct', 0)}%
• Engagement rate: {eng_str}
• Impression score: {metrics.get('impression_score', 0):,}
• Audience mood: {metrics.get('audience_mood', 'unknown')}

═══ TOP PERFORMING POSTS (by views) ═══
{posts_str}
═══ HASHTAG ANALYSIS ═══
All-time most used tags: {', '.join(all_top_tags) if all_top_tags else '(none)'}

🔺 TRENDING NOW (rising in recent posts vs older posts):
{_tag_line(trending_tags)}
🔻 FADING (were popular before, less so now):
{_tag_line(fading_tags)}
➡ STABLE (consistent usage):
{_tag_line(stable_tags)}

═══ AUDIENCE TOPICS FROM COMMENTS ═══
{topics_str}

═══ CREATOR PERFORMANCE (ranked by comment volume) ═══
{creators_str}
═══ POSITIVE COMMENT SAMPLES ═══
{fmt_comments(positive_comments)}
═══ NEGATIVE COMMENT SAMPLES ═══
{fmt_comments(negative_comments)}

Generate a structured JSON report. Respond with ONLY valid JSON — no markdown, no explanation.

{{
  "summary": "3–4 sentence executive summary. Lead with overall performance verdict, then key numbers (views, sentiment, engagement), then one forward-looking sentence.",
  "sentiment_insights": "2–3 sentences. Explain WHAT is driving positive reactions and WHAT is causing negative ones, based on the actual comment samples and topics above.",
  "what_worked": [
    "5 specific things that performed well — cite actual metrics, hashtags, topic names, or creator names from the data."
  ],
  "what_to_improve": [
    "5 specific, actionable improvement areas — each tied to a concrete data point from above."
  ],
  "recommendations": [
    "5 strategic recommendations for the next campaign period — specific enough to act on, including which hashtags to use or avoid."
  ],
  "risk_alerts": [
    "2–3 concrete risks to monitor — e.g. a spike in negative sentiment, a fading hashtag still being over-used, a low-engagement creator."
  ],
  "audience_insights": [
    "3–4 behavioral observations about the audience — language mix, engagement patterns, topics they care about most, how they interact with hashtags."
  ],
  "trending_now": [
    "3–5 content signals that are rising right now — name specific hashtags, topics, or content formats that are gaining momentum and explain why they matter for this campaign."
  ],
  "fading_content": [
    "2–4 content signals that are losing traction — name specific hashtags or topics that were strong before but are declining, and suggest whether to drop or pivot them."
  ],
  "content_strategy": [
    "4–6 specific content/hashtag strategy recommendations — e.g. double down on #X because it is trending, replace #Y with #Z, post at the cadence seen in top-performing content."
  ]
}}

Important rules:
- Every bullet must be 1–2 sentences, specific, and tied to the data above.
- Do NOT invent facts not present in the data. If data is limited, say so briefly.
- Reference actual hashtags (with #), percentages, view counts, and creator usernames where relevant.
- Write with the Tunisian/North-African market context in mind (multilingual audience: Arabic, Darija, French).
"""

    def _parse_response(self, text: str) -> Optional[Dict[str, Any]]:
        clean = re.sub(r"```(?:json)?\s*|\s*```", "", text).strip()
        try:
            parsed = json.loads(clean)
            missing = _REQUIRED_KEYS - set(parsed.keys())
            if missing:
                logger.warning("AI report missing keys: %s", missing)
                for k in missing:
                    parsed[k] = [] if k not in ("summary", "sentiment_insights") else ""
            return {
                "summary":            str(parsed.get("summary", "")),
                "sentiment_insights": str(parsed.get("sentiment_insights", "")),
                "what_worked":        [str(x) for x in parsed.get("what_worked", [])],
                "what_to_improve":    [str(x) for x in parsed.get("what_to_improve", [])],
                "recommendations":    [str(x) for x in parsed.get("recommendations", [])],
                "risk_alerts":        [str(x) for x in parsed.get("risk_alerts", [])],
                "audience_insights":  [str(x) for x in parsed.get("audience_insights", [])],
                "trending_now":       [str(x) for x in parsed.get("trending_now", [])],
                "fading_content":     [str(x) for x in parsed.get("fading_content", [])],
                "content_strategy":   [str(x) for x in parsed.get("content_strategy", [])],
            }
        except (json.JSONDecodeError, TypeError, KeyError) as exc:
            logger.warning("Failed to parse AI report: %s — snippet: %s", exc, text[:300])
            return None


def _fmt_num(n: float) -> str:
    n = int(n or 0)
    if n >= 1_000_000:
        return f"{n/1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n/1_000:.1f}K"
    return str(n)
