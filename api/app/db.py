"""Async SQLAlchemy engine and session plumbing for the app database.

This is the drafting-side store (speeches, sections, section sources, voice
profiles) and is entirely separate from Qdrant, which holds the embedded
corpus. See app/models.py for the schema.
"""
import logging
from collections.abc import AsyncIterator
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import event
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings

logger = logging.getLogger(__name__)

engine = create_async_engine(settings.app_database_url, future=True)

SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


@event.listens_for(engine.sync_engine, "connect")
def _sqlite_pragmas(dbapi_connection, _connection_record) -> None:
    """SQLite defaults that the schema depends on.

    foreign_keys is OFF by default and is a *per-connection* setting -- without
    this every ON DELETE CASCADE / SET NULL in models.py is silently decorative.
    WAL keeps a long read (fetching a speech tree) from blocking a write.
    """
    if not settings.app_database_url.startswith("sqlite"):
        return
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.close()


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding a request-scoped session.

    Deliberately does *not* commit on teardown: FastAPI runs yield-dependency
    teardown after the response has been handed to the client, so a caller could
    see its own write 204 and then read stale data on the next request. Write
    endpoints commit explicitly before returning instead.
    """
    async with SessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


def run_migrations() -> None:
    """Upgrade the app database to head.

    Called from the lifespan hook. Safe to run on every boot because the api is
    single-replica (see the _SESSIONS comment in main.py); if it is ever scaled
    out this becomes an explicit deploy step instead.
    """
    api_root = Path(__file__).resolve().parent.parent

    url = make_url(settings.app_database_url)
    if url.drivername.startswith("sqlite") and url.database:
        Path(url.database).parent.mkdir(parents=True, exist_ok=True)

    config = Config(str(api_root / "alembic.ini"))
    config.set_main_option("script_location", str(api_root / "migrations"))
    config.set_main_option("sqlalchemy.url", settings.app_database_url)
    command.upgrade(config, "head")
    logger.info("App database migrated to head")
