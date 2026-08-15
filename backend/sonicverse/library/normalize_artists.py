"""Split combined artist credits into individual Artist rows."""

from __future__ import annotations

from sqlalchemy import or_, select

from sonicverse.core.artists import (
    artist_name_key,
    normalize_album_title,
    normalize_artist_name,
    split_artist_names,
)
from sonicverse.models import Album, Artist, Track
from sonicverse.models.track_artist import track_artists


async def normalize_combined_artists(session, *, commit: bool = True) -> int:
    """Split ``A, B & C`` artist rows into individuals and re-link tracks/albums.

    Returns how many combined artist rows were rewritten.
    """
    result = await session.execute(
        select(Artist).where(
            or_(
                Artist.name.contains(","),
                Artist.name.contains(";"),
                Artist.name.contains("；"),
                Artist.name.contains("&"),
                Artist.name.contains("/"),
                Artist.name.contains("、"),
            )
        )
    )
    combined = list(result.scalars().all())
    if not combined:
        return 0

    rewritten = 0
    for artist in combined:
        names = split_artist_names(artist.name)
        if len(names) <= 1:
            continue

        people: list[Artist] = []
        for name in names:
            found = await session.execute(
                select(Artist).where(Artist.name == name).order_by(Artist.id)
            )
            person = found.scalars().first()
            if person is None:
                person = Artist(name=name)
                session.add(person)
                await session.flush()
            people.append(person)
        primary = people[0]
        people_ids = {person.id for person in people}

        albums = await session.execute(select(Album).where(Album.artist_id == artist.id))
        for album in albums.scalars().all():
            album.artist_id = primary.id

        track_ids: set[str] = set()
        primary_tracks = await session.execute(
            select(Track).where(Track.artist_id == artist.id)
        )
        for track in primary_tracks.scalars().all():
            track_ids.add(track.id)

        credited = await session.execute(
            select(Track).where(
                Track.id.in_(
                    select(track_artists.c.track_id).where(
                        track_artists.c.artist_id == artist.id
                    )
                )
            )
        )
        for track in credited.scalars().all():
            track_ids.add(track.id)

        if track_ids:
            tracks = await session.execute(select(Track).where(Track.id.in_(track_ids)))
            for track in tracks.scalars().all():
                await session.refresh(track, attribute_names=["artists"])
                if track.artist_id == artist.id:
                    track.artist_id = primary.id
                merged = [item for item in track.artists if item.id != artist.id]
                seen = {item.id for item in merged}
                for person in people:
                    if person.id not in seen:
                        merged.append(person)
                        seen.add(person.id)
                # Prefer split credit order when the old row was the only credit.
                if not seen - people_ids:
                    merged = list(people)
                track.artists = merged

        await session.delete(artist)
        rewritten += 1

    if rewritten:
        if commit:
            await session.commit()
        else:
            await session.flush()
    return rewritten


def _preferred_artist(people: list[Artist]) -> Artist:
    return min(
        people,
        key=lambda artist: (
            0 if artist.avatar_path else 1,
            0 if artist.mbid else 1,
            artist.id,
        ),
    )


async def _repoint_artist(session, extra: Artist, keeper: Artist) -> None:
    albums = await session.execute(select(Album).where(Album.artist_id == extra.id))
    for album in albums.scalars().all():
        album.artist_id = keeper.id

    tracks = await session.execute(
        select(Track).where(
            or_(
                Track.artist_id == extra.id,
                Track.id.in_(
                    select(track_artists.c.track_id).where(
                        track_artists.c.artist_id == extra.id
                    )
                ),
            )
        )
    )
    for track in tracks.scalars().all():
        await session.refresh(track, attribute_names=["artists"])
        if track.artist_id == extra.id:
            track.artist_id = keeper.id
        merged = [item for item in track.artists if item.id != extra.id]
        if all(item.id != keeper.id for item in merged):
            merged.append(keeper)
        track.artists = merged

    if extra.mbid and not keeper.mbid:
        keeper.mbid = extra.mbid
    extra.mbid = None
    if extra.avatar_path and not keeper.avatar_path:
        keeper.avatar_path = extra.avatar_path


async def merge_duplicate_artists(session, *, commit: bool = True) -> int:
    """Collapse artist rows that are the same person under different ids."""
    result = await session.execute(select(Artist))
    groups: dict[str, list[Artist]] = {}
    for artist in result.scalars().all():
        key = artist_name_key(artist.name)
        if not key:
            continue
        groups.setdefault(key, []).append(artist)

    merged = 0
    changed = False
    for people in groups.values():
        keeper = people[0] if len(people) == 1 else _preferred_artist(people)
        canonical = normalize_artist_name(keeper.name)
        if keeper.name != canonical:
            keeper.name = canonical
            changed = True
        if len(people) == 1:
            continue
        for extra in people:
            if extra.id == keeper.id:
                continue
            await _repoint_artist(session, extra, keeper)
            await session.delete(extra)
            merged += 1
            changed = True

    if changed:
        if commit:
            await session.commit()
        else:
            await session.flush()
    return merged


def _album_title_key(title: str | None) -> str:
    return normalize_album_title(title).casefold()


def _preferred_album(albums: list[Album]) -> Album:
    return min(
        albums,
        key=lambda album: (
            0 if album.cover_path else 1,
            0 if album.mbid else 1,
            0 if album.year else 1,
            album.id,
        ),
    )


async def _repoint_album(session, extra: Album, keeper: Album) -> None:
    tracks = await session.execute(select(Track).where(Track.album_id == extra.id))
    for track in tracks.scalars().all():
        track.album_id = keeper.id
    if extra.year is not None and keeper.year is None:
        keeper.year = extra.year
    if extra.cover_path and not keeper.cover_path:
        keeper.cover_path = extra.cover_path
    if extra.mbid and not keeper.mbid:
        keeper.mbid = extra.mbid
    extra.mbid = None


async def merge_duplicate_albums(session, *, commit: bool = True) -> int:
    """Collapse albums that share a title under the same artist."""
    result = await session.execute(select(Album))
    groups: dict[tuple[str, str], list[Album]] = {}
    for album in result.scalars().all():
        title_key = _album_title_key(album.title)
        if not title_key:
            continue
        groups.setdefault((album.artist_id or "", title_key), []).append(album)

    merged = 0
    changed = False
    for releases in groups.values():
        keeper = releases[0] if len(releases) == 1 else _preferred_album(releases)
        canonical = normalize_album_title(keeper.title)
        if keeper.title != canonical:
            keeper.title = canonical
            changed = True
        if len(releases) == 1:
            continue
        for extra in releases:
            if extra.id == keeper.id:
                continue
            await _repoint_album(session, extra, keeper)
            await session.delete(extra)
            merged += 1
            changed = True

    if changed:
        if commit:
            await session.commit()
        else:
            await session.flush()
    return merged


async def heal_library_rows(session, *, commit: bool = True) -> int:
    """Split combined artist credits, then collapse duplicate artists and albums."""
    split = await normalize_combined_artists(session, commit=False)
    people = await merge_duplicate_artists(session, commit=False)
    releases = await merge_duplicate_albums(session, commit=False)
    changed = split + people + releases
    if changed:
        if commit:
            await session.commit()
        else:
            await session.flush()
    return changed
