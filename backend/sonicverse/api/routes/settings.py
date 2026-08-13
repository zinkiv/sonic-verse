"""Settings API routes."""

from fastapi import APIRouter

from sonicverse.core.config import get_settings
from sonicverse.core.user_settings import (
    get_match_confidence_threshold,
    set_match_confidence_threshold,
)
from sonicverse.schemas.settings import SettingsUpdate

router = APIRouter(prefix="/settings", tags=["settings"])


def _settings_payload() -> dict:
    cfg = get_settings()
    return {
        "app_version": cfg.app_version,
        "music_path": cfg.music_path,
        "transfer_path": cfg.transfer_path,
        "covers_path": cfg.covers_path,
        "data_path": str(cfg.data_path),
        "database_type": cfg.database_type,
        "database_engine": "sqlite" if cfg.is_sqlite else "postgresql",
        "audio_extensions": cfg.audio_extensions,
        "match_confidence_threshold": get_match_confidence_threshold(),
    }


@router.get("")
async def read_settings() -> dict:
    """Effective configuration: env defaults plus persisted UI overrides."""
    return _settings_payload()


@router.patch("")
async def update_settings(data: SettingsUpdate) -> dict:
    """Persist UI-editable settings (match threshold)."""
    set_match_confidence_threshold(data.match_confidence_threshold)
    return _settings_payload()
