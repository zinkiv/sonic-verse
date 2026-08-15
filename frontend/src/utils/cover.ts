/** Build a cover image URL that bypasses browser/proxy caches after updates. */
export function coverSrc(
  path: string | null | undefined,
  version?: string | number | null
): string | undefined {
  if (!path) return undefined
  if (path.includes('?')) return path
  if (version == null || version === '') return path
  return `${path}?v=${encodeURIComponent(String(version))}`
}

export type TrackCoverSource = 'file' | 'album' | 'auto'

/** Cover endpoint. Metadata queue / current track use embedded `file` art. */
export function trackCoverSrc(
  trackId: string,
  version?: string | number | null,
  source: TrackCoverSource = 'auto'
): string {
  const params = new URLSearchParams()
  if (source !== 'auto') params.set('source', source)
  if (version != null && version !== '') params.set('v', String(version))
  const query = params.toString()
  return `/api/v1/tracks/${trackId}/cover${query ? `?${query}` : ''}`
}
