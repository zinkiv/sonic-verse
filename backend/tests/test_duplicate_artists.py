"""Duplicate artist rows with the same display name are collapsed."""

from sonicverse.matcher.apply import _overwrite_album, _overwrite_artists
from sonicverse.models import Album, Artist, Track


async def test_list_artists_merges_identical_names(client, session):
    matched = Artist(name="倉木麻衣", avatar_path="/covers/mai.jpg")
    leftover = Artist(name="倉木麻衣")
    session.add_all([matched, leftover])
    await session.flush()
    album = Album(title="Beautiful Days", artist_id=matched.id)
    session.add(album)
    await session.flush()
    session.add_all(
        [
            Track(
                title="Reach for the sky",
                artist_id=matched.id,
                album_id=album.id,
                file_path="/music/mai1.flac",
            ),
            Track(
                title="Secret of my heart",
                artist_id=leftover.id,
                album_id=album.id,
                file_path="/music/mai2.flac",
            ),
        ]
    )
    await session.commit()

    body = (await client.get("/api/v1/artists")).json()
    names = [item["name"] for item in body["items"]]
    assert names.count("倉木麻衣") == 1
    kuraki = next(item for item in body["items"] if item["name"] == "倉木麻衣")
    assert kuraki["avatar_path"] == "/covers/mai.jpg"
    assert kuraki["id"] == matched.id


async def test_overwrite_artists_reuses_existing_same_name(session):
    existing = Artist(name="倉木麻衣")
    tagged = Artist(name="Mai Kuraki")
    session.add_all([existing, tagged])
    await session.flush()
    album = Album(title="Delicious Way", artist_id=existing.id)
    session.add(album)
    await session.flush()
    owned = Track(
        title="Stay by my side",
        artist_id=existing.id,
        album_id=album.id,
        file_path="/music/stay.flac",
    )
    exclusive = Track(
        title="Love, Day After Tomorrow",
        artist_id=tagged.id,
        album_id=album.id,
        file_path="/music/love.flac",
    )
    session.add_all([owned, exclusive])
    await session.flush()

    artists = await _overwrite_artists(session, exclusive, "倉木麻衣")
    assert [item.id for item in artists] == [existing.id]


async def test_list_albums_merges_same_title_same_artist(client, session):
    artist = Artist(name="周杰伦")
    session.add(artist)
    await session.flush()
    kept = Album(title="叶惠美", artist_id=artist.id, cover_path="/covers/ye.jpg", year=2003)
    extra = Album(title="叶惠美", artist_id=artist.id)
    session.add_all([kept, extra])
    await session.flush()
    session.add_all(
        [
            Track(
                title="晴天",
                artist_id=artist.id,
                album_id=kept.id,
                file_path="/music/qt.flac",
            ),
            Track(
                title="以父之名",
                artist_id=artist.id,
                album_id=extra.id,
                file_path="/music/yf.flac",
            ),
        ]
    )
    await session.commit()

    body = (await client.get("/api/v1/albums")).json()
    titles = [item["title"] for item in body["items"]]
    assert titles.count("叶惠美") == 1
    album = next(item for item in body["items"] if item["title"] == "叶惠美")
    assert album["id"] == kept.id
    assert album["cover_path"] == "/covers/ye.jpg"
    assert album["track_count"] == 2


async def test_overwrite_album_reuses_existing_same_title(session):
    artist = Artist(name="周杰伦")
    session.add(artist)
    await session.flush()
    existing = Album(title="叶惠美", artist_id=artist.id, year=2003)
    tagged = Album(title="Yeh Hui Mei", artist_id=artist.id)
    session.add_all([existing, tagged])
    await session.flush()
    owned = Track(
        title="晴天",
        artist_id=artist.id,
        album_id=existing.id,
        file_path="/music/qt2.flac",
    )
    exclusive = Track(
        title="以父之名",
        artist_id=artist.id,
        album_id=tagged.id,
        file_path="/music/yf2.flac",
    )
    session.add_all([owned, exclusive])
    await session.flush()

    album = await _overwrite_album(
        session, exclusive, "叶惠美", artist, year=2003, mbid=None
    )
    assert album.id == existing.id
