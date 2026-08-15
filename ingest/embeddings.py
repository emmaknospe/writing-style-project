"""Gemini embeddings via Vertex AI, authenticated with Application Default
Credentials (`gcloud auth application-default login`, or a service-account
key referenced by GOOGLE_APPLICATION_CREDENTIALS). No API key needed.
"""
import logging
import os
import time

from google import genai
from google.genai.types import EmbedContentConfig

logger = logging.getLogger(__name__)

DEFAULT_MODEL = os.environ.get("GEMINI_EMBEDDING_MODEL", "gemini-embedding-001")
DEFAULT_LOCATION = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")


def build_client() -> genai.Client:
    project = os.environ.get("GOOGLE_CLOUD_PROJECT")
    if not project:
        raise RuntimeError(
            "GOOGLE_CLOUD_PROJECT must be set to the GCP project ADC should "
            "authorize against (see .env.example)."
        )
    return genai.Client(vertexai=True, project=project, location=DEFAULT_LOCATION)


def embed_text(
    client,
    text,
    *,
    model=DEFAULT_MODEL,
    output_dimensionality=1536,
    task_type="RETRIEVAL_DOCUMENT",
    max_retries=5,
    retry_delay_seconds=2.0,
):
    """Embed a single chunk of text.

    The Vertex AI embed_content endpoint for gemini-embedding-001 accepts
    one input per request (no server-side batching), so callers loop over
    chunks rather than passing a list.
    """
    for attempt in range(1, max_retries + 1):
        try:
            response = client.models.embed_content(
                model=model,
                contents=text,
                config=EmbedContentConfig(
                    task_type=task_type,
                    output_dimensionality=output_dimensionality,
                ),
            )
            return response.embeddings[0].values
        except Exception as exc:
            logger.warning(
                "Embedding call failed (attempt %d/%d): %s", attempt, max_retries, exc
            )
            if attempt == max_retries:
                raise
            time.sleep(retry_delay_seconds * attempt)
