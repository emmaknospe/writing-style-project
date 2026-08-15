import logging
import time

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams

from app.config import settings

logger = logging.getLogger(__name__)

qdrant_client = QdrantClient(url=settings.qdrant_url)


def ensure_collection(max_retries: int = 10, retry_delay_seconds: float = 2.0) -> None:
    """Idempotently ensure the configured collection exists.

    Retries with backoff since Qdrant may still be starting when this runs
    (there is no compose-level healthcheck gating startup order).
    """
    for attempt in range(1, max_retries + 1):
        try:
            if not qdrant_client.collection_exists(settings.qdrant_collection_name):
                qdrant_client.create_collection(
                    collection_name=settings.qdrant_collection_name,
                    vectors_config=VectorParams(
                        size=settings.qdrant_vector_size,
                        distance=Distance.COSINE,
                    ),
                )
                logger.info("Created Qdrant collection %r", settings.qdrant_collection_name)
            else:
                logger.info("Qdrant collection %r already exists", settings.qdrant_collection_name)
            return
        except Exception as exc:
            logger.warning("Qdrant not ready (attempt %d/%d): %s", attempt, max_retries, exc)
            if attempt == max_retries:
                raise
            time.sleep(retry_delay_seconds)
