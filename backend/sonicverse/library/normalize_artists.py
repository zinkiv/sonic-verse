"""Split combined artist credits into individual Artist rows."""

from __future__ import annotations

from sqlalchemy import or_, select

from sonicverse.core.artists import split_artist_names
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
            found = await session.execute(select(Artist).where(Artist.name == name))
            person = found.scalar_one_or_none()
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
