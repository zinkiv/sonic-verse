"""Configuration management for SonicVerse."""

from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from sonicverse.core.version import resolve_app_version
from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DatabaseType = Literal["sqlite", "postgresql"]

_DEFAULT_SQLITE_NAME = "sonicverse.db"
_DEFAULT_SQLITE_DIR = "database"


def _normalize_postgres_url(url: str) -> str:
    """Convert postgres:// / postgresql:// URLs to SQLAlchemy asyncpg form."""
    if url.startswith("postgres://"):
        url = "postgresql+asyncpg://" + url.removeprefix("postgres://")
    elif url.startswith("postgresql://"):
        url = "postgresql+asyncpg://" + url.removeprefix("postgresql://")
    elif not url.startswith("postgresql+asyncpg://"):
        url = "postgresql+asyncpg://" + url

    # asyncpg does not accept libpq's sslmode; drop or map it.
    parsed = urlparse(url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    sslmode = query.pop("sslmode", None)
    if sslmode and "ssl" not in query:
        # prefer/allow → omit (asyncpg default); require/verify-* → ssl=true
        if sslmode in {"require", "verify-ca", "verify-full"}:
            query["ssl"] = "true"
    return urlunparse(parsed._replace(query=urlencode(query)))


class Settings(BaseSettings):
    """Application settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # Application
    app_name: str = "SonicVerse"
    # Overridable via APP_VERSION; Docker image bakes the git tag into /app/VERSION.
    app_version: str = ""
    debug: bool = False

    @field_validator("app_version", mode="before")
    @classmethod
    def default_app_version(cls, value: object) -> str:
        if isinstance(value, str) and value.strip():
            return value.strip()
        return resolve_app_version()

    # Database: sqlite (default) or postgresql.
    # Empty database_url always falls back to local SQLite under data_path/database/.
    # Empty DATABASE_TYPE is treated as sqlite (so image ENV can leave it blank).
    database_type: DatabaseType = "sqlite"
    database_url: str = ""

    # Paths: music library; transfer staging lives under data_path by default.
    # logs_path is container-local by default in Docker (not on the /data volume).
    music_path: str = "/music"
    transfer_path: str = "./data/transfer"
    data_path: Path = Path("./data")
    logs_path: Path = Path("./logs")

    # API
    api_prefix: str = "/api/v1"
    cors_origins: list[str] = [
        "http://localhost:3000",
        "http://localhost:5173",
        "http://localhost:7526",
    ]

    # MusicBrainz
    musicbrainz_user_agent: str = "SonicVerse/0.1.0 (contact@example.com)"

    # Scanning
    scan_batch_size: int = 100
    audio_extensions: list[str] = [".mp3", ".flac", ".m4a", ".ogg", ".wav", ".ape"]

    # Matching (0–100 percent; legacy 0–1 fractions still accepted via clamp)
    match_confidence_threshold: float = 100

    @field_validator("database_type", mode="before")
    @classmethod
    def empty_database_type(cls, value: object) -> object:
        if value is None or (isinstance(value, str) and not value.strip()):
            return "sqlite"
        return value

    @property
    def covers_path(self) -> str:
        return str(self.data_path / "covers")

    @property
    def library_path(self) -> Path:
        return self.data_path / "library"

    def _default_sqlite_url(self) -> str:
        db_file = (self.data_path / _DEFAULT_SQLITE_DIR / _DEFAULT_SQLITE_NAME).as_posix()
        return f"sqlite+aiosqlite:///{db_file}"

    @model_validator(mode="after")
    def resolve_database(self) -> "Settings":
        """Resolve effective database_url from type + optional connection string.

        - No connection URL → local SQLite under ``data_path/database/``.
        - Explicit ``sqlite…`` URL is kept (e.g. tests).
        - Postgres-looking URL → PostgreSQL via asyncpg (even if type left as sqlite).
        - ``database_type=postgresql`` requires a Postgres ``database_url``.
        """
        raw_url = (self.database_url or "").strip()
        db_type = (self.database_type or "sqlite").lower()

        if not raw_url:
            if db_type == "postgresql":
                raise ValueError(
                    "DATABASE_TYPE=postgresql requires DATABASE_URL "
                    "(e.g. postgres://user:pass@host:5432/dbname)"
                )
            object.__setattr__(self, "database_type", "sqlite")
            object.__setattr__(self, "database_url", self._default_sqlite_url())
            return self

        if "sqlite" in raw_url:
            object.__setattr__(self, "database_type", "sqlite")
            object.__setattr__(self, "database_url", raw_url)
            return self

        looks_postgres = raw_url.startswith(
            ("postgres://", "postgresql://", "postgresql+asyncpg://")
        )
        if looks_postgres or db_type == "postgresql":
            object.__setattr__(self, "database_type", "postgresql")
            object.__setattr__(self, "database_url", _normalize_postgres_url(raw_url))
            return self

        object.__setattr__(self, "database_type", "sqlite")
        object.__setattr__(self, "database_url", self._default_sqlite_url())
        return self

    @property
    def is_sqlite(self) -> bool:
        return self.database_type == "sqlite" or "sqlite" in self.database_url

    @property
    def sqlite_db_path(self) -> Path | None:
        """Filesystem path of the SQLite file, if using SQLite."""
        if not self.is_sqlite:
            return None
        return self.data_path / _DEFAULT_SQLITE_DIR / _DEFAULT_SQLITE_NAME


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
