"""
Embedding service using Google's text-embedding-004 model.
Generates vector embeddings for campaigns and creators to enable
real cosine-similarity matching.
"""
import json
import logging
from typing import List, Optional

import google.generativeai as genai
from app.config import settings

logger = logging.getLogger(__name__)

_MODEL = "models/gemini-embedding-002"


class EmbeddingService:
    def __init__(self):
        genai.configure(api_key=settings.GOOGLE_API_KEY)

    def generate_embedding(self, text: str) -> Optional[List[float]]:
        """Generate a single embedding vector for the given text."""
        if not text or not text.strip():
            return None
        try:
            result = genai.embed_content(
                model=_MODEL,
                content=text,
                task_type="semantic_similarity",
            )
            embedding = result["embedding"]
            logger.info("Embedding generated: %d dimensions for %d chars",
                        len(embedding), len(text))
            return embedding
        except Exception as exc:
            logger.error("Embedding generation failed: %s", exc)
            return None

    def build_creator_text(
        self,
        username: str,
        bio: Optional[str],
        topics: List[str],
        mood: Optional[str],
    ) -> str:
        """Build a text representation of a creator for embedding."""
        parts = [f"Creator @{username}"]
        if bio:
            parts.append(f"Bio: {bio}")
        if topics:
            parts.append(f"Content topics: {', '.join(topics)}")
        if mood:
            parts.append(f"Audience mood: {mood}")
        return ". ".join(parts)

    def build_campaign_text(
        self,
        name: str,
        brand: str,
        description: Optional[str],
        keywords: List[str],
    ) -> str:
        """Build a text representation of a campaign for embedding."""
        parts = [f"Campaign: {name} by {brand}"]
        if description:
            parts.append(f"Description: {description}")
        if keywords:
            parts.append(f"Target keywords: {', '.join(keywords)}")
        return ". ".join(parts)
