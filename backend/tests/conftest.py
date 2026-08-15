"""Shared test fixtures.

The environment is pointed at a throwaway directory *before* anything from
``sonicverse`` is imported, because ``get_settings`` is lru_cached and the
database engine is built at import time.
"""

import os
import shutil
import tempfile
from pathlib import Path

_TMP_ROOT = Path(tempfile.mkdtemp(prefix="sonicverse-tests-"))
_MUSIC = _TMP_ROOT / "music"
_TRANSFER = _TMP_ROOT / "transfer"
_DATA = _TMP_ROOT / "data"
_LOGS = _TMP_ROOT / "logs"
for _path in (_MUSIC, _TRANSFER, _DATA, _DATA / "covers", _DATA / "database", _DATA / "library", _LOGS):
    _path.mkdir(parents=True, exist_ok=True)

os.environ["DATABASE_URL"] = (
    f"sqlite+aiosqlite:///{(_DATA / 'database' / 'test.db').as_posix()}"
)
os.environ["MUSIC_PATH"] = str(_MUSIC)
os.environ["TRANSFER_PATH"] = str(_TRANSFER)
os.environ["DATA_PATH"] = str(_DATA)
os.environ["LOGS_PATH"] = str(_LOGS)
os.environ["MATCH_CONFIDENCE_THRESHOLD"] = "1.0"
os.environ["AUTH_SECRET"] = "test-auth-secret"

import pytest  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

from sonicverse.core.database import Base, async_session_maker, engine  # noqa: E402
from sonicverse.core.auth import AuthUser, hash_password, issue_token  # noqa: E402
from sonicverse.main import app  # noqa: E402
from sonicverse.models import Album, Artist, Track, User  # noqa: E402


def pytest_sessionfinish(session, exitstatus):
    shutil.rmtree(_TMP_ROOT, ignore_errors=True)


@pytest.fixture(autouse=True)
def _reset_user_settings():
    path = _DATA / "user_settings.json"
    if path.exists():
        path.unlink()
    yield
    if path.exists():
        path.unlink()


@pytest.fixture
def music_root() -> Path:
    return _MUSIC


@pytest.fixture
def transfer_root() -> Path:
    return _TRANSFER


@pytest.fixture
async def clean_db():
    """Give each test an empty schema on the real engine."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield


@pytest.fixture
async def session(clean_db):
    async with async_session_maker() as s:
        yield s


@pytest.fixture
async def client(session):
    admin = User(
        username="admin",
        password_hash=hash_password("admin123"),
        role="admin",
        disabled=False,
    )
    session.add(admin)
    await session.commit()
    await session.refresh(admin)
    token = issue_token(
        AuthUser(id=admin.id, username=admin.username, role=admin.role, disabled=False)
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"Authorization": f"Bearer {token}"},
    ) as ac:
        yield ac


@pytest.fixture
async def anon_client(clean_db):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
async def library(session):
    """A tiny library: one artist, one album, three tracks."""
    artist = Artist(name="周杰伦")
    session.add(artist)
    await session.flush()

    album = Album(title="叶惠美", artist_id=artist.id, year=2003)
    session.add(album)
    await session.flush()

    tracks = [
        Track(
            title=title,
            artist_id=artist.id,
            album_id=album.id,
            track_number=index,
            duration_ms=200_000 + index,
            file_path=f"/music/{title}.flac",
        )
        for index, title in enumerate(["以父之名", "晴天", "三年二班"], start=1)
    ]
    session.add_all(tracks)
    await session.commit()

    return {"artist": artist, "album": album, "tracks": tracks}
