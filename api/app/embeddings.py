"""Gemini query embeddings via Vertex AI, for RAG retrieval at chat time.

Mirrors ingest/embeddings.py's client + retry logic, but is a separate copy
(api/ and ingest/ are independently deployable; api/Dockerfile only COPYs
app/) and always embeds with task_type="RETRIEVAL_QUERY" -- the asymmetric
counterpart to ingest's RETRIEVAL_DOCUMENT chunks. Model + output_dimensionality
must match ingest time or query vectors won't be comparable to stored vectors.
"""
import logging
import time

from google import genai
from google.genai.types import EmbedContentConfig

from app.config import settings

logger = logging.getLogger(__name__)

genai_client = genai.Client(
    vertexai=True,
    project=settings.google_cloud_project,
    location=settings.google_cloud_location,
)


def embed_query(text: str, *, max_retries: int = 5, retry_delay_seconds: float = 2.0) -> list[float]:
    """Embed a single query string for retrieval against the ingested corpus."""
    for attempt in range(1, max_retries + 1):
        try:
            response = genai_client.models.embed_content(
                model=settings.gemini_embedding_model,
                contents=text,
                config=EmbedContentConfig(
                    task_type="RETRIEVAL_QUERY",
                    output_dimensionality=settings.qdrant_vector_size,
                ),
            )
            return response.embeddings[0].values
        except Exception as exc:
            logger.warning("Query embedding failed (attempt %d/%d): %s", attempt, max_retries, exc)
            if attempt == max_retries:
                raise
            time.sleep(retry_delay_seconds * attempt)
