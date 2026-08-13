"""Database configuration and session management."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy import event
from sqlalchemy.exc import DBAPIError, OperationalError
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from sonicverse.core.config import get_settings


class Base(DeclarativeBase):
    """SQLAlchemy declarative base."""

    pass


settings = get_settings()


def _engine_kwargs() -> dict:
    """Build create_async_engine kwargs for the active database backend."""
    kwargs: dict = {
        "echo": settings.debug,
        "pool_pre_ping": True,
    }
    if settings.is_sqlite:
        kwargs["connect_args"] = {"timeout": 15}
        return kwargs

    # Postgres / asyncpg: recycle before typical idle kills (PgBouncer, cloud PG),
    # and avoid holding dead connections after long HTTP work.
    kwargs.update(
        {
            "pool_size": 10,
            "max_overflow": 20,
            "pool_recycle": 1800,
            "pool_timeout": 30,
            "connect_args": {
                "timeout": 30,
                "command_timeout": 120,
            },
        }
    )
    return kwargs


engine = create_async_engine(settings.database_url, **_engine_kwargs())

if settings.is_sqlite:
    # WAL mode + busy timeout so a background scan can write while the API reads.
    @event.listens_for(engine.sync_engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=15000")
        cursor.execute("PRAGMA synchronous=NORMAL")
        # SQLite defaults to OFF, which silently disables every ondelete= rule.
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

async_session_maker = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


def is_disconnect_error(exc: BaseException) -> bool:
    """True when the DB connection dropped mid-operation (common with Postgres)."""
    if isinstance(exc, (OperationalError, DBAPIError)) and getattr(exc, "connection_invalidated", False):
        return True
    text = str(exc).lower()
    markers = (
        "connectiondoesnotexist",
        "connection was closed",
        "connection is closed",
        "server closed the connection",
        "connection reset",
        "broken pipe",
    )
    return any(marker in text for marker in markers)


async def init_db() -> None:
    """Initialize database tables and apply lightweight column patches."""
    # Ensure association tables are registered on Base.metadata.
    import sonicverse.models  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_add_missing_columns)


def _add_missing_columns(sync_conn) -> None:
    """Add columns introduced after initial create_all (no Alembic yet)."""
    from sqlalchemy import inspect, text

    inspector = inspect(sync_conn)
    tables = set(inspector.get_table_names())

    if "match_jobs" in tables:
        cols = {c["name"] for c in inspector.get_columns("match_jobs")}
        if "scope" not in cols:
            sync_conn.execute(
                text(
                    "ALTER TABLE match_jobs "
                    "ADD COLUMN scope VARCHAR(32) NOT NULL DEFAULT 'pending'"
                )
            )
        if "force_refresh_images" not in cols:
            default = "0" if settings.is_sqlite else "FALSE"
            sync_conn.execute(
                text(
                    "ALTER TABLE match_jobs "
                    f"ADD COLUMN force_refresh_images BOOLEAN NOT NULL DEFAULT {default}"
                )
            )

    if "artists" in tables:
        cols = {c["name"] for c in inspector.get_columns("artists")}
        if "avatar_path" not in cols:
            sync_conn.execute(
                text("ALTER TABLE artists ADD COLUMN avatar_path VARCHAR(512)")
            )

    if "tracks" in tables:
        cols = {c["name"] for c in inspector.get_columns("tracks")}
        if "tag_title" not in cols:
            sync_conn.execute(text("ALTER TABLE tracks ADD COLUMN tag_title VARCHAR(255)"))
        if "tag_artist" not in cols:
            sync_conn.execute(text("ALTER TABLE tracks ADD COLUMN tag_artist VARCHAR(255)"))
        if "tag_album" not in cols:
            sync_conn.execute(text("ALTER TABLE tracks ADD COLUMN tag_album VARCHAR(255)"))
        if "tag_has_cover" not in cols:
            sync_conn.execute(text("ALTER TABLE tracks ADD COLUMN tag_has_cover BOOLEAN"))


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency for getting database session.

    Read-only by default: routes that mutate data must commit explicitly.
    """
    async with async_session_maker() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


@asynccontextmanager
async def get_db_context() -> AsyncGenerator[AsyncSession, None]:
    """Context manager for database session."""
    async with async_session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
