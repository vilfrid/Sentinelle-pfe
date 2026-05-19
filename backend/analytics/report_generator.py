"""
AI-powered report generator using Google Gemini.
Generates comprehensive campaign performance reports with executive summaries,
sentiment insights, risk alerts, audience analysis, and actionable recommendations.
"""
import json
import logging
import re
from typing import Optional, Dict, Any, List

import google.generativeai as genai
from app.config import settings

logger = logging.getLogger(__name__)

_RETRY_ATTEMPTS = 2
_REQUIRED_KEYS = {
    "summary", "sentiment_insights", "what_worked",
    "what_to_improve", "recommendations", "risk_alerts", "audience_insights",
}


class ReportGenerator:
    def __init__(self):
        genai.configure(api_key=settings.GOOGLE_API_KEY)
        self.model = genai.GenerativeModel("gemini-2.0-flash")

    def generate(
        self,
        campaign_name: str,
        brand: str,
        metrics: Dict[str, Any],
        trending_topics: List[Dict],
        sample_comments: List[Dict],
        creator_summaries: List[Dict],
    ) -> Dict[str, Any]:
        prompt = self._build_prompt(
            campaign_name, brand, metrics, trending_topics,
            sample_comments, creator_summaries,
        )

        for attempt in range(_RETRY_ATTEMPTS):
            try:
                response = self.model.generate_content(prompt)
                parsed = self._parse_response(response.text)
                if parsed:
                    logger.info("Report generated for '%s'", campaign_name)
                    return parsed
            except Exception as exc:
                logger.warning("Report generation attempt %d failed: %s", attempt + 1, exc)

        logger.warning("AI report generation failed — using fallback")
        return self._fallback_report(campaign_name, brand, metrics)

    def _build_prompt(
        self,
        campaign_name: str,
        brand: str,
        metrics: Dict[str, Any],
        trending_topics: List[Dict],
        sample_comments: List[Dict],
        creator_summaries: List[Dict],
    ) -> str:
        # Topics
        topics_str = ", ".join(
            [t.get("topic", "") for t in (trending_topics or [])[:15]]
        ) or "No trending topics detected"

        # Split comments by sentiment
        positive_comments = [c for c in sample_comments if c.get("sentiment") == "positive"][:8]
        negative_comments = [c for c in sample_comments if c.get("sentiment") == "negative"][:8]

        def fmt_comments(lst: List[Dict]) -> str:
            if not lst:
                return "  (none)\n"
            return "".join(f'  - "{c.get("text", "")[:180]}"\n' for c in lst)

        # Creator ranking
        sorted_creators = sorted(
            creator_summaries or [],
            key=lambda c: c.get("total_comments", 0),
            reverse=True,
        )
        creators_str = ""
        for i, cr in enumerate(sorted_creators[:8], 1):
            pos = cr.get("positive_pct", 0)
            neg = cr.get("negative_pct", 0)
            mood = cr.get("mood", "?")
            total = cr.get("total_comments", 0)
            creators_str += (
                f"  #{i} @{cr.get('username', '?')}: "
                f"{total} comments · {pos}% positive · {neg}% negative · mood: {mood}\n"
            )
        if not creators_str:
            creators_str = "  No creator data available.\n"

        # Engagement display
        eng = metrics.get("engagement_rate", 0)
        eng_str = f"{eng * 100:.2f}%" if eng > 0 else "N/A (no view data)"

        return f"""You are a senior social media analytics consultant specializing in the Tunisian and North-African digital market.
Analyze the data below and generate a comprehensive campaign performance report.

═══ CAMPAIGN ═══
Name: "{campaign_name}"
Brand: {brand}

═══ KEY METRICS ═══
• Total comments analyzed: {metrics.get('total_comments', 0)}
• Posts tracked: {metrics.get('total_posts', 0)}
• Positive sentiment: {metrics.get('positive_pct', 0)}%
• Negative sentiment: {metrics.get('negative_pct', 0)}%
• Neutral sentiment: {metrics.get('neutral_pct', 0)}%
• Engagement rate: {eng_str}
• Impression score: {metrics.get('impression_score', 0):,}
• Audience mood: {metrics.get('audience_mood', 'unknown')}

═══ TRENDING TOPICS ═══
{topics_str}

═══ CREATOR PERFORMANCE (ranked by volume) ═══
{creators_str}
═══ POSITIVE COMMENT SAMPLES ═══
{fmt_comments(positive_comments)}
═══ NEGATIVE COMMENT SAMPLES ═══
{fmt_comments(negative_comments)}

Generate a structured JSON report. Respond with ONLY valid JSON — no markdown, no explanation.

{{
  "summary": "3–4 sentence executive summary. Lead with overall performance verdict, then key numbers, then one forward-looking sentence.",
  "sentiment_insights": "2–3 sentences. Explain WHAT is driving positive reactions and WHAT is causing negative ones, based on the actual comment samples and topics above.",
  "what_worked": [
    "5 specific things that performed well — cite actual metrics, topic names, or creator names."
  ],
  "what_to_improve": [
    "5 specific, actionable improvement areas — each tied to a concrete data point from above."
  ],
  "recommendations": [
    "5 strategic recommendations for the next campaign period — specific enough to act on."
  ],
  "risk_alerts": [
    "2–3 concrete risks to monitor — e.g. a spike in negative sentiment around a specific topic, a low-engagement creator, or a recurring complaint theme."
  ],
  "audience_insights": [
    "3–4 behavioral observations about the audience — language mix, engagement patterns, topics they care about most."
  ]
}}

Important rules:
- Every bullet must be 1–2 sentences, specific, and tied to the data above.
- Do NOT invent facts not present in the data. If data is limited, say so briefly.
- Reference actual topic names, percentages, and creator usernames where relevant.
- Write with the Tunisian/North-African market context in mind (multilingual audience: Arabic, Darija, French).
"""

    def _parse_response(self, text: str) -> Optional[Dict[str, Any]]:
        clean = re.sub(r"```(?:json)?\s*|\s*```", "", text).strip()
        try:
            parsed = json.loads(clean)
            missing = _REQUIRED_KEYS - set(parsed.keys())
            if missing:
                logger.warning("AI report missing keys: %s", missing)
                # Fill missing optional sections with empty defaults rather than failing
                for k in missing:
                    parsed[k] = [] if k != "summary" and k != "sentiment_insights" else ""
            return {
                "summary": str(parsed.get("summary", "")),
                "sentiment_insights": str(parsed.get("sentiment_insights", "")),
                "what_worked": [str(x) for x in parsed.get("what_worked", [])],
                "what_to_improve": [str(x) for x in parsed.get("what_to_improve", [])],
                "recommendations": [str(x) for x in parsed.get("recommendations", [])],
                "risk_alerts": [str(x) for x in parsed.get("risk_alerts", [])],
                "audience_insights": [str(x) for x in parsed.get("audience_insights", [])],
            }
        except (json.JSONDecodeError, TypeError, KeyError) as exc:
            logger.warning("Failed to parse AI report: %s — snippet: %s", exc, text[:300])
            return None

    def _fallback_report(
        self, campaign_name: str, brand: str, metrics: Dict[str, Any]
    ) -> Dict[str, Any]:
        total = metrics.get("total_comments", 0)
        pos_pct = metrics.get("positive_pct", 0)
        neg_pct = metrics.get("negative_pct", 0)
        mood = metrics.get("audience_mood", "unknown")

        summary = (
            f"Campaign '{campaign_name}' by {brand} analyzed {total} comments. "
            f"Overall audience mood: {mood}. "
            f"Sentiment split: {pos_pct}% positive, {neg_pct}% negative."
        )

        what_worked, what_to_improve, risk_alerts = [], [], []

        if pos_pct > 60:
            what_worked.append("Strong positive audience reception overall.")
        if metrics.get("engagement_rate", 0) > 0.05:
            what_worked.append("Above-average engagement rate detected.")
        if neg_pct > 30:
            what_to_improve.append("Address recurring negative feedback themes in comments.")
            risk_alerts.append(f"Negative sentiment at {neg_pct}% — monitor for escalation.")
        if metrics.get("engagement_rate", 0) == 0:
            what_to_improve.append("View data not captured — consider platforms with richer analytics.")

        return {
            "summary": summary,
            "sentiment_insights": (
                f"Positive sentiment accounts for {pos_pct}% of comments. "
                f"Negative accounts for {neg_pct}%. "
                "Run AI report generation when Gemini is available for deeper analysis."
            ),
            "what_worked": what_worked or ["Insufficient data for detailed analysis."],
            "what_to_improve": what_to_improve or ["Gather more data for deeper insights."],
            "recommendations": [
                "Continue monitoring sentiment trends regularly.",
                "Focus content on topics driving positive engagement.",
            ],
            "risk_alerts": risk_alerts or ["No critical risks detected with available data."],
            "audience_insights": ["More data needed for detailed audience behavior analysis."],
        }
