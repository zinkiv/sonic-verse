import type { ArtistSummary, Track } from '@/api'

/** Split credits on English commas, semicolons, ampersands, slashes, or 顿号 — not 「，」. */
export function splitArtistNames(raw: string | null | undefined): string[] {
  if (!raw?.trim()) return []
  const parts = raw
    .split(/\s*[,;；&/、]\s*/)
    .map((part) => part.trim())
    .filter(Boolean)
  if (parts.length === 0) return [raw.trim()]

  const names: string[] = []
  const seen = new Set<string>()
  for (const part of parts) {
    const key = part.toLocaleLowerCase()
    if (seen.has(key)) continue
    seen.add(key)
    names.push(part)
  }
  return names
}

export function trackArtistLabel(track: Track): string {
  const credits =
    track.artists && track.artists.length > 0
      ? [...track.artists]
      : track.artist
        ? [track.artist]
        : []
  if (credits.length === 0) return ''
  if (track.artist_id) {
    credits.sort((a, b) => {
      if (a.id === track.artist_id) return -1
      if (b.id === track.artist_id) return 1
      return a.name.localeCompare(b.name)
    })
  }
  return formatArtistCredits(credits)
}

export function formatArtistCredits(artists: ArtistSummary[]): string {
  return artists.map((artist) => artist.name).join(',')
}

export function formatArtistName(name: string | null | undefined): string {
  const parts = splitArtistNames(name)
  return parts.join(',')
}
