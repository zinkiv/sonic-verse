"""Provider registry."""

from sonicverse.providers.base import BaseProvider
from sonicverse.providers.netease import NeteaseProvider
from sonicverse.providers.qqmusic import QQMusicProvider

# Tie-break when scores tie: QQ Music first, then NetEase.
SEARCH_PROVIDERS: tuple[str, ...] = ("qqmusic", "netease")
# Batch organize: QQ first; NetEase if QQ empty/fails or best score < 100%.
BATCH_SEARCH_PROVIDERS: tuple[str, ...] = ("qqmusic", "netease")
PROVIDER_NAMES = SEARCH_PROVIDERS

_PROVIDERS: dict[str, type[BaseProvider]] = {
    "netease": NeteaseProvider,
    "qqmusic": QQMusicProvider,
}


def get_provider(name: str) -> BaseProvider:
    """Instantiate a metadata provider by name."""
    key = (name or "").strip().lower()
    cls = _PROVIDERS.get(key)
    if cls is None:
        raise ValueError(f"Unknown provider: {name}")
    return cls()


def provider_rank(name: str | None) -> int:
    """Lower is higher priority. Unknown sources sort last."""
    key = (name or "").strip().lower()
    try:
        return SEARCH_PROVIDERS.index(key)
    except ValueError:
        return len(SEARCH_PROVIDERS)
