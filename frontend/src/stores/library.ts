import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import {
  api,
  type Album,
  type Artist,
  type MusicSyncResponse,
  type PaginatedResponse,
  type ScanJob,
  type Stats,
  type Track,
} from '@/api'
import { i18n } from '@/i18n'

export type SubTab = 'albums' | 'artists' | 'tracks'

const SUB_TAB_ENDPOINT: Record<SubTab, string> = {
  albums: '/albums',
  artists: '/artists',
  tracks: '/tracks',
}

const PAGE_SIZE: Record<SubTab, number> = {
  // Multiples of common grid column counts (6/8/12) so full pages fill rows.
  albums: 48,
  artists: 48,
  tracks: 20,
}

function errorMessage(err: unknown, fallbackKey: string): string {
  return err instanceof Error ? err.message : i18n.global.t(fallbackKey)
}

function usesInfiniteScroll(tab: SubTab): boolean {
  return tab === 'albums' || tab === 'artists'
}

export const useLibraryStore = defineStore('library', () => {
  const albums = ref<Album[]>([])
  const artists = ref<Artist[]>([])
  const tracks = ref<Track[]>([])
  const stats = ref<Stats>({
    total_tracks: 0,
    total_albums: 0,
    total_artists: 0,
    missing_covers: 0,
    unknown_artists: 0,
    missing_albums: 0,
    pending_review: 0,
    transfer_pending: 0,
  })

  const currentSubTab = ref<SubTab>('albums')
  const search = ref('')
  const loading = ref(false)
  const loadingMore = ref(false)
  const syncing = ref(false)
  const error = ref<string | null>(null)

  // When set, the tracks tab only shows songs for this album/artist.
  const filterAlbumId = ref<string | null>(null)
  const filterArtistId = ref<string | null>(null)
  const filterLabel = ref<string | null>(null)

  // Pagination state of the currently loaded list
  const page = ref(1)
  const pageSize = ref(PAGE_SIZE.albums)
  const total = ref(0)
  const totalPages = ref(0)

  const isEmpty = computed(() => total.value === 0)
  const hasTrackFilter = computed(
    () => filterAlbumId.value !== null || filterArtistId.value !== null
  )
  const hasMore = computed(
    () =>
      usesInfiniteScroll(currentSubTab.value) &&
      totalPages.value > 0 &&
      page.value < totalPages.value
  )
  const metadataResyncTick = ref(0)

  // Typing in the search box fires overlapping requests; only the newest one
  // is allowed to write its result into the store.
  let requestSeq = 0
  let syncPollTimer: ReturnType<typeof setTimeout> | undefined
  let syncSeq = 0

  function clearSyncPoll() {
    clearTimeout(syncPollTimer)
    syncPollTimer = undefined
  }

  function applyPagination(data: PaginatedResponse<unknown>) {
    page.value = data.page
    pageSize.value = data.page_size
    total.value = data.total
    totalPages.value = data.total_pages
  }

  function clearTrackFilterState() {
    filterAlbumId.value = null
    filterArtistId.value = null
    filterLabel.value = null
  }

  function resetPagerFor(tab: SubTab) {
    page.value = 1
    pageSize.value = PAGE_SIZE[tab]
    total.value = 0
    totalPages.value = 0
  }

  function appendUnique<T extends { id: string }>(existing: T[], incoming: T[]): T[] {
    const seen = new Set(existing.map((item) => item.id))
    return [...existing, ...incoming.filter((item) => !seen.has(item.id))]
  }

  async function fetchStats() {
    try {
      stats.value = await api.get<Stats>('/stats')
    } catch (err) {
      error.value = errorMessage(err, 'errors.statsFailed')
    }
  }

  async function reloadLibrary() {
    albums.value = []
    artists.value = []
    tracks.value = []
    clearTrackFilterState()
    page.value = 1
    total.value = 0
    totalPages.value = 0
    await Promise.all([fetchStats(), fetchList(1)])
  }

  async function pollMusicSync(jobId: string, seq: number) {
    try {
      const job = await api.get<ScanJob>(`/scanner/jobs/${jobId}`)
      if (seq !== syncSeq) return

      if (job.status === 'pending' || job.status === 'running') {
        syncPollTimer = setTimeout(() => void pollMusicSync(jobId, seq), 800)
        return
      }

      await reloadLibrary()
    } catch (err) {
      if (seq === syncSeq) {
        error.value = errorMessage(err, 'errors.loadFailed')
      }
    }

    if (seq === syncSeq) {
      clearSyncPoll()
      syncing.value = false
    }
  }

  async function syncMusicFromDisk() {
    const seq = ++syncSeq
    clearSyncPoll()
    syncing.value = true
    try {
      const result = await api.post<MusicSyncResponse>('/scanner/sync-music')
      if (seq !== syncSeq) return

      if (!result.changed || !result.job) {
        syncing.value = false
        return
      }

      await pollMusicSync(result.job.id, seq)
    } catch (err) {
      if (seq === syncSeq) {
        syncing.value = false
        error.value = errorMessage(err, 'errors.loadFailed')
      }
    }
  }

  async function fetchList(pageNum = page.value, options?: { append?: boolean }) {
    const append = Boolean(options?.append)
    const seq = ++requestSeq
    const tab = currentSubTab.value
    const size = PAGE_SIZE[tab]

    if (append) loadingMore.value = true
    else loading.value = true
    error.value = null
    try {
      const data = await api.get<PaginatedResponse<Album | Artist | Track>>(
        SUB_TAB_ENDPOINT[tab],
        {
          page: pageNum,
          page_size: size,
          ...(search.value ? { search: search.value } : {}),
          ...(tab === 'tracks' && filterAlbumId.value
            ? { album_id: filterAlbumId.value }
            : {}),
          ...(tab === 'tracks' && filterArtistId.value
            ? { artist_id: filterArtistId.value }
            : {}),
        }
      )

      if (seq !== requestSeq) return

      if (tab === 'albums') {
        albums.value = append
          ? appendUnique(albums.value, data.items as Album[])
          : (data.items as Album[])
      } else if (tab === 'artists') {
        artists.value = append
          ? appendUnique(artists.value, data.items as Artist[])
          : (data.items as Artist[])
      } else {
        tracks.value = data.items as Track[]
      }

      applyPagination(data)
    } catch (err) {
      if (seq !== requestSeq) return
      error.value = errorMessage(err, 'errors.loadFailed')
    } finally {
      if (seq === requestSeq) {
        loading.value = false
        loadingMore.value = false
      }
    }
  }

  async function loadMore() {
    if (!hasMore.value || loading.value || loadingMore.value) return
    await fetchList(page.value + 1, { append: true })
  }

  function setSubTab(tab: SubTab) {
    if (currentSubTab.value === tab) {
      // Clicking「曲目」again while filtered returns to the full track list.
      if (tab === 'tracks' && hasTrackFilter.value) {
        clearTrackFilterState()
        resetPagerFor('tracks')
        tracks.value = []
        return fetchList(1)
      }
      return
    }
    clearTrackFilterState()
    currentSubTab.value = tab
    // Reset pager immediately so albums/artists don't keep the previous tab's
    // page count (e.g. tracks had 6 pages while artists only need 1).
    resetPagerFor(tab)
    albums.value = []
    artists.value = []
    tracks.value = []
    return fetchList(1)
  }

  function setSearch(query: string) {
    if (search.value === query) return
    search.value = query
    return fetchList(1)
  }

  function goToPage(pageNum: number) {
    const target = Math.min(Math.max(pageNum, 1), Math.max(totalPages.value, 1))
    if (target === page.value) return
    return fetchList(target)
  }

  function showAlbumTracks(album: Album) {
    filterAlbumId.value = album.id
    filterArtistId.value = null
    filterLabel.value = album.title
    currentSubTab.value = 'tracks'
    resetPagerFor('tracks')
    tracks.value = []
    return fetchList(1)
  }

  function showArtistTracks(artist: Artist) {
    filterArtistId.value = artist.id
    filterAlbumId.value = null
    filterLabel.value = artist.name
    currentSubTab.value = 'tracks'
    resetPagerFor('tracks')
    tracks.value = []
    return fetchList(1)
  }

  function clearTrackFilter() {
    if (!hasTrackFilter.value) return
    clearTrackFilterState()
    if (currentSubTab.value === 'tracks') return fetchList(1)
  }

  async function deleteAlbum(albumId: string) {
    await api.delete(`/albums/${albumId}`)
    albums.value = albums.value.filter((album) => album.id !== albumId)
    total.value = Math.max(0, total.value - 1)
    await fetchStats()
    if (albums.value.length === 0 && total.value > 0) {
      await fetchList(1)
    }
  }

  async function deleteTrack(trackId: string) {
    await api.delete(`/tracks/${trackId}`)
    await Promise.all([fetchList(page.value), fetchStats()])
    if (tracks.value.length === 0 && page.value > 1) {
      await fetchList(page.value - 1)
    }
  }

  async function matchArtist(artistId: string, provider = 'qqmusic') {
    const updated = await api.post<Artist>(
      `/artists/${artistId}/match`,
      undefined,
      { provider },
    )
    const index = artists.value.findIndex((artist) => artist.id === artistId)
    if (index >= 0) {
      artists.value[index] = updated
    }
    return updated
  }

  function bumpMetadataResync() {
    metadataResyncTick.value += 1
  }

  return {
    albums,
    artists,
    tracks,
    stats,
    currentSubTab,
    search,
    loading,
    loadingMore,
    syncing,
    error,
    filterAlbumId,
    filterArtistId,
    filterLabel,
    hasTrackFilter,
    hasMore,
    page,
    pageSize,
    total,
    totalPages,
    isEmpty,
    metadataResyncTick,
    fetchStats,
    fetchList,
    loadMore,
    reloadLibrary,
    syncMusicFromDisk,
    bumpMetadataResync,
    setSubTab,
    setSearch,
    goToPage,
    showAlbumTracks,
    showArtistTracks,
    clearTrackFilter,
    deleteAlbum,
    deleteTrack,
    matchArtist,
  }
})
