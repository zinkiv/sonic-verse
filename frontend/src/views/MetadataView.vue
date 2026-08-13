<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import {
  api,
  AUDIO_ACCEPT,
  type AppSettings,
  type MatchCandidate,
  type MatchCandidatesResponse,
  type MatchJob,
  type MetadataIssue,
  type MetadataProvider,
  type MusicSyncResponse,
  type PaginatedResponse,
  type ScanJob,
  type Track,
} from '@/api'
import { useLibraryStore } from '@/stores/library'
import { trackCoverSrc } from '@/utils/cover'
import { formatArtistName, trackArtistLabel } from '@/utils/artists'

const { t } = useI18n()
const route = useRoute()
const router = useRouter()
const libraryStore = useLibraryStore()

type IssueFilter = MetadataIssue
type LibraryIssueFilter = Exclude<IssueFilter, 'transfer' | 'all'>

const PROVIDERS: { value: MetadataProvider; labelKey: string }[] = [
  { value: 'netease', labelKey: 'metadata.providerNetease' },
  { value: 'qqmusic', labelKey: 'metadata.providerQq' },
]

const ISSUE_OPTIONS: { value: LibraryIssueFilter; labelKey: string; dot: string }[] = [
  { value: 'missing_album', labelKey: 'metadata.missingAlbums', dot: 'purple' },
  { value: 'missing_cover', labelKey: 'metadata.missingCovers', dot: 'yellow' },
  { value: 'unknown_artist', labelKey: 'metadata.unknownArtists', dot: 'red' },
]

const VALID_ISSUES: IssueFilter[] = ['transfer', ...ISSUE_OPTIONS.map((option) => option.value)]

const activeIssue = ref<IssueFilter>('transfer')
const provider = ref<MetadataProvider>('netease')
const queue = ref<Track[]>([])
const queueTotal = ref(0)
const queuePage = ref(1)
const queuePageSize = ref(20)
const queueTotalPages = ref(0)
const selectedId = ref<string | null>(null)
const candidates = ref<MatchCandidate[]>([])

const loadingQueue = ref(false)
const matching = ref(false)
const saving = ref(false)
const error = ref<string | null>(null)
const statusMessage = ref<string | null>(null)

const editorOpen = ref(false)
const editForm = ref({
  title: '',
  artist: '',
  album: '',
  year: '' as string,
  mbid: '',
  album_mbid: '' as string,
  duration: 0,
  cover_url: null as string | null,
  artist_image_url: null as string | null,
  artist_images: null as { name: string; url: string }[] | null,
  provider: 'netease' as MetadataProvider,
  score: 0,
})

const musicPath = ref<string | null>(null)
const transferPath = ref<string | null>(null)
const matchPercent = ref(100)
const pendingDelete = ref<Track | null>(null)
const deleting = ref(false)
const deleteError = ref<string | null>(null)
const scanJob = ref<ScanJob | null>(null)
const scanBusy = ref(false)
const matchJob = ref<MatchJob | null>(null)
const matchBusy = ref(false)
const uploadBusy = ref(false)
const uploadInput = ref<HTMLInputElement | null>(null)
let pollTimer: ReturnType<typeof setTimeout> | undefined
let matchPollTimer: ReturnType<typeof setTimeout> | undefined

const selectedTrack = computed(
  () => queue.value.find((track) => track.id === selectedId.value) ?? null
)

const issueCounts = computed<Record<LibraryIssueFilter, number>>(() => ({
  missing_album: libraryStore.stats.missing_albums,
  missing_cover: libraryStore.stats.missing_covers,
  unknown_artist: libraryStore.stats.unknown_artists,
}))

const isScanning = computed(() => {
  const status = scanJob.value?.status
  return status === 'pending' || status === 'running'
})

const isBatchMatching = computed(() => {
  const status = matchJob.value?.status
  return status === 'pending' || status === 'running'
})

const workspaceBusy = computed(
  () => matching.value || saving.value || matchBusy.value || isBatchMatching.value
)
function formatDuration(ms: number | null | undefined): string {
  if (!ms) return '--:--'
  const seconds = Math.floor(ms / 1000)
  const mins = Math.floor(seconds / 60)
  const secs = seconds % 60
  return `${mins}:${secs.toString().padStart(2, '0')}`
}

function scorePercent(candidate: MatchCandidate): number {
  const raw = candidate.score || candidate.confidence || 0
  // New API: 0–100. Legacy stored candidates: 0–1 fractions.
  const percent = raw <= 1 ? Math.round(raw * 100) : Math.round(raw)
  return Math.min(100, Math.max(0, percent))
}

function providerLabel(name: string | null | undefined): string {
  if (name === 'qqmusic') return t('metadata.providerQq')
  return t('metadata.providerNetease')
}

function clearPoll() {
  clearTimeout(pollTimer)
  pollTimer = undefined
}

function clearMatchPoll() {
  clearTimeout(matchPollTimer)
  matchPollTimer = undefined
}

function schedulePoll(jobId: string) {
  clearPoll()
  pollTimer = setTimeout(() => void pollJob(jobId), 1000)
}

function scheduleMatchPoll(jobId: string) {
  clearMatchPoll()
  matchPollTimer = setTimeout(() => void pollMatchJob(jobId), 1000)
}

async function pollJob(jobId: string) {
  try {
    const job = await api.get<ScanJob>(`/scanner/jobs/${jobId}`)
    scanJob.value = job

    if (job.status === 'pending' || job.status === 'running') {
      schedulePoll(jobId)
      return
    }

    scanBusy.value = false
    if (job.status === 'completed') {
      statusMessage.value = t('metadata.scanCompleted', { processed: job.tracks_processed })
      await libraryStore.fetchStats()
      activeIssue.value = 'transfer'
      queuePage.value = 1
      await loadQueue(selectedId.value)
    } else if (job.status === 'failed') {
      error.value = t('metadata.scanFailed', {
        error: job.error_msg || t('errors.loadFailed'),
      })
    }
  } catch (err) {
    scanBusy.value = false
    error.value = err instanceof Error ? err.message : t('metadata.scanStartFailed')
  }
}

async function pollMatchJob(jobId: string) {
  try {
    const job = await api.get<MatchJob>(`/match-jobs/${jobId}`)
    matchJob.value = job

    if (job.status === 'pending' || job.status === 'running') {
      scheduleMatchPoll(jobId)
      return
    }

    matchBusy.value = false
    if (job.status === 'completed' || job.status === 'cancelled') {
      statusMessage.value = t('metadata.batchMatchCompleted', {
        auto: job.auto_applied,
        review: job.needs_review,
        unmatched: job.unmatched,
        failed: job.failed,
      })
      await libraryStore.fetchStats()
      activeIssue.value = 'transfer'
      queuePage.value = 1
      await loadQueue(selectedId.value)
      if (selectedId.value) {
        await loadStoredCandidates(selectedId.value)
      }
    } else if (job.status === 'failed') {
      error.value = t('metadata.batchMatchFailed', {
        error: job.error_msg || t('errors.loadFailed'),
      })
    }
  } catch (err) {
    matchBusy.value = false
    error.value = err instanceof Error ? err.message : t('metadata.batchMatchStartFailed')
  }
}

async function startOrganize() {
  if (matchBusy.value || isBatchMatching.value || isScanning.value) return

  matchBusy.value = true
  error.value = null
  statusMessage.value = null
  closeEditor()
  candidates.value = []

  try {
    const job = await api.post<MatchJob>('/tracks/batch-match', {
      auto_apply: true,
      scope: 'transfer',
    })
    matchJob.value = job
    scheduleMatchPoll(job.id)
  } catch (err) {
    matchBusy.value = false
    error.value = err instanceof Error ? err.message : t('metadata.batchMatchStartFailed')
  }
}

async function startScan() {
  if (!transferPath.value || isScanning.value || scanBusy.value) return

  scanBusy.value = true
  error.value = null
  statusMessage.value = null

  try {
    const job = await api.post<ScanJob>('/scanner/scan', {
      root_path: transferPath.value,
    })
    scanJob.value = job
    schedulePoll(job.id)
  } catch (err) {
    scanBusy.value = false
    error.value = err instanceof Error ? err.message : t('metadata.scanStartFailed')
  }
}

function pickUpload() {
  if (uploadBusy.value || workspaceBusy.value) return
  uploadInput.value?.click()
}

async function handleUpload(event: Event) {
  const input = event.target as HTMLInputElement
  const files = input.files ? Array.from(input.files) : []
  input.value = ''

  if (files.length === 0 || uploadBusy.value) return

  uploadBusy.value = true
  error.value = null
  statusMessage.value = null
  closeEditor()
  candidates.value = []

  try {
    const formData = new FormData()
    for (const file of files) {
      formData.append('files', file)
    }
    const imported = await api.upload<Track[]>('/upload', formData)
    if (imported.length === 0) {
      error.value = t('metadata.uploadFailed')
      return
    }

    await libraryStore.fetchStats()
    activeIssue.value = 'transfer'
    queuePage.value = 1
    await loadQueue(imported[0].id)
    statusMessage.value = t('metadata.uploadMatching', { count: imported.length })
  } catch (err) {
    error.value = err instanceof Error ? err.message : t('metadata.uploadFailed')
  } finally {
    uploadBusy.value = false
  }
}

async function syncTransferFromDisk(): Promise<boolean> {
  if (!transferPath.value) return false

  try {
    const result = await api.post<MusicSyncResponse>('/scanner/sync-transfer')
    if (result.changed && result.job) {
      scanBusy.value = true
      scanJob.value = result.job
      schedulePoll(result.job.id)
      return true
    }
    return false
  } catch (err) {
    error.value = err instanceof Error ? err.message : t('metadata.scanStartFailed')
    return false
  }
}

async function bootstrapMetadataPage(preferId?: string | null) {
  await libraryStore.fetchStats()
  const scanStarted = await syncTransferFromDisk()
  if (scanStarted) return

  await loadQueue(preferId ?? null)

  if (preferId && selectedId.value !== preferId) {
    try {
      const track = await api.get<Track>(`/tracks/${preferId}`)
      queue.value = [track, ...queue.value.filter((item) => item.id !== preferId)]
      selectedId.value = track.id
    } catch {
      // Keep the queue selection if the deep-link track is gone.
    }
  }

  if (selectedId.value) {
    await loadStoredCandidates(selectedId.value)
  }
}

async function loadQueue(preferId?: string | null) {
  loadingQueue.value = true
  error.value = null
  try {
    const data = await api.get<PaginatedResponse<Track>>('/tracks', {
      page: queuePage.value,
      page_size: queuePageSize.value,
      issue: activeIssue.value,
    })
    queue.value = data.items
    queueTotal.value = data.total
    queueTotalPages.value = data.total_pages
    if (data.total_pages > 0 && queuePage.value > data.total_pages) {
      queuePage.value = data.total_pages
      await loadQueue(preferId)
      return
    }

    const keepId = preferId && data.items.some((item) => item.id === preferId)
      ? preferId
      : data.items[0]?.id ?? null
    selectedId.value = keepId
  } catch (err) {
    error.value = err instanceof Error ? err.message : t('errors.loadFailed')
    queue.value = []
    queueTotal.value = 0
    queueTotalPages.value = 0
    selectedId.value = null
  } finally {
    loadingQueue.value = false
  }
}

function goQueuePage(page: number) {
  if (page < 1 || (queueTotalPages.value > 0 && page > queueTotalPages.value)) return
  if (page === queuePage.value) return
  queuePage.value = page
  void loadQueue(null)
}

function openDeleteTrack(track: Track, event: Event) {
  event.preventDefault()
  event.stopPropagation()
  if (deleting.value || workspaceBusy.value) return
  deleteError.value = null
  pendingDelete.value = track
}

function closeDeleteConfirm() {
  if (deleting.value) return
  pendingDelete.value = null
  deleteError.value = null
}

async function confirmDeleteTrack() {
  const track = pendingDelete.value
  if (!track || deleting.value) return

  deleting.value = true
  deleteError.value = null
  try {
    await api.delete(`/tracks/${track.id}`)
    pendingDelete.value = null
    if (selectedId.value === track.id) {
      closeEditor()
      candidates.value = []
    }
    const preferId = selectedId.value === track.id ? null : selectedId.value
    await Promise.all([loadQueue(preferId), libraryStore.fetchStats()])
    statusMessage.value = t('metadata.deleteSuccess')
  } catch (err) {
    deleteError.value = err instanceof Error ? err.message : t('metadata.deleteFailed')
  } finally {
    deleting.value = false
  }
}

async function loadStoredCandidates(trackId: string) {
  try {
    const data = await api.get<MatchCandidatesResponse>(`/tracks/${trackId}/candidates`)
    candidates.value = data.candidates
  } catch {
    candidates.value = []
  }
}

async function runMatch(trackId: string) {
  matching.value = true
  error.value = null
  statusMessage.value = null
  candidates.value = []
  closeEditor()

  try {
    const data = await api.post<MatchCandidatesResponse>(`/tracks/${trackId}/match`, {
      provider: provider.value,
    })
    candidates.value = data.candidates
    if (data.candidates.length === 0) {
      statusMessage.value = t('metadata.noCandidatesHint')
    }
  } catch (err) {
    error.value = err instanceof Error ? err.message : t('metadata.matchFailed')
  } finally {
    matching.value = false
  }
}

function queryMetadata() {
  if (!selectedTrack.value || workspaceBusy.value) return
  void runMatch(selectedTrack.value.id)
}

function openCandidate(candidate: MatchCandidate) {
  editForm.value = {
    title: candidate.title,
    artist: formatArtistName(candidate.artist) || candidate.artist,
    album: candidate.album,
    year: candidate.year != null ? String(candidate.year) : '',
    mbid: candidate.mbid,
    album_mbid: candidate.album_mbid ?? '',
    duration: candidate.duration || 0,
    cover_url: candidate.cover_url ?? null,
    artist_image_url: candidate.artist_image_url ?? null,
    artist_images: candidate.artist_images ?? null,
    provider: candidate.provider || provider.value,
    score: scorePercent(candidate),
  }
  editorOpen.value = true
}

function closeEditor() {
  editorOpen.value = false
}

async function saveEditedMetadata() {
  const track = selectedTrack.value
  if (!track || saving.value) return

  const title = editForm.value.title.trim()
  const artist = editForm.value.artist.trim()
  const album = editForm.value.album.trim()
  if (!title || !artist) {
    error.value = t('metadata.editRequired')
    return
  }

  saving.value = true
  error.value = null
  statusMessage.value = null
  try {
    const yearRaw = editForm.value.year.trim()
    const year = yearRaw ? Number.parseInt(yearRaw, 10) : null
    await api.post<Track>(`/tracks/${track.id}/apply`, {
      title,
      artist,
      album: album || title,
      mbid: editForm.value.mbid,
      album_mbid: editForm.value.album_mbid || null,
      year: Number.isFinite(year) ? year : null,
      duration: editForm.value.duration || null,
      fetch_cover: true,
      cover_url: editForm.value.cover_url,
      artist_image_url: editForm.value.artist_image_url,
      artist_images: editForm.value.artist_images,
      provider: editForm.value.provider,
    })
    closeEditor()
    statusMessage.value = t('metadata.saveSuccess')
    await libraryStore.fetchStats()
    await loadQueue(null)
  } catch (err) {
    error.value = err instanceof Error ? err.message : t('metadata.saveFailed')
  } finally {
    saving.value = false
  }
}

function selectIssue(issue: LibraryIssueFilter) {
  activeIssue.value = activeIssue.value === issue ? 'transfer' : issue
  queuePage.value = 1
}

function selectTrack(track: Track) {
  if (selectedId.value === track.id) return
  selectedId.value = track.id
}

function hideBrokenCover(event: Event) {
  const img = event.target as HTMLImageElement | null
  if (img) img.style.display = 'none'
}

function queueTitle(track: Track): string {
  return track.file_tags?.title || track.title
}

function queueArtist(track: Track): string {
  return track.file_tags?.artist || trackArtistLabel(track)
}

watch(selectedId, (id) => {
  candidates.value = []
  closeEditor()
  statusMessage.value = null
  if (id) {
    void loadStoredCandidates(id)
  }
})

let suppressIssueReload = false

watch(activeIssue, () => {
  if (suppressIssueReload) return
  void loadQueue(null)
})

onMounted(async () => {
  await libraryStore.fetchStats()
  try {
    const settings = await api.get<AppSettings>('/settings')
    musicPath.value = settings.music_path
    transferPath.value = settings.transfer_path
    const raw = settings.match_confidence_threshold ?? 100
    const percent = raw <= 1 ? Math.round(raw * 100) : Math.round(raw)
    matchPercent.value = Number.isFinite(percent)
      ? Math.min(100, Math.max(50, percent))
      : 100
  } catch {
    musicPath.value = null
    transferPath.value = null
  }

  const queryTrackId =
    typeof route.query.track === 'string' && route.query.track ? route.query.track : null
  const queryIssue =
    typeof route.query.issue === 'string' && VALID_ISSUES.includes(route.query.issue as IssueFilter)
      ? (route.query.issue as IssueFilter)
      : null
  const autoMatch = route.query.auto === '1'

  suppressIssueReload = true
  if (queryIssue) {
    activeIssue.value = queryIssue
  }
  suppressIssueReload = false

  await bootstrapMetadataPage(queryTrackId)

  if (queryTrackId || queryIssue || autoMatch) {
    const nextQuery = { ...route.query }
    delete nextQuery.track
    delete nextQuery.issue
    delete nextQuery.auto
    void router.replace({ query: nextQuery })
  }
})

watch(
  () => libraryStore.metadataResyncTick,
  () => {
    if (route.name !== 'metadata') return
    void bootstrapMetadataPage(selectedId.value)
  }
)

onBeforeUnmount(() => {
  clearPoll()
  clearMatchPoll()
})
</script>

<template>
  <div class="main-wrapper">
    <div class="meta-layout">
      <!-- Left Sidebar -->
      <div class="meta-sidebar">
        <div class="sidebar-card">
          <h3>{{ t('metadata.quickActions') }}</h3>
          <div class="quick-actions">
            <button
              class="quick-btn"
              :disabled="!transferPath || isScanning || scanBusy"
              @click="startScan"
            >
              <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"/>
              </svg>
              {{ isScanning || scanBusy ? t('metadata.scanningLibrary') : t('metadata.scan') }}
            </button>
            <button
              class="quick-btn"
              :disabled="!transferPath || matchBusy || isBatchMatching || isScanning || scanBusy"
              :title="t('metadata.organizeHint', { threshold: matchPercent })"
              @click="startOrganize"
            >
              <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4"/>
              </svg>
              {{ isBatchMatching || matchBusy ? t('metadata.organizing') : t('metadata.organize') }}
            </button>
            <button
              class="quick-btn"
              :disabled="!transferPath || uploadBusy || workspaceBusy"
              @click="pickUpload"
            >
              <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12"/>
              </svg>
              {{ uploadBusy ? t('metadata.uploading') : t('metadata.upload') }}
            </button>
            <input
              ref="uploadInput"
              type="file"
              class="upload-input"
              :accept="AUDIO_ACCEPT"
              multiple
              @change="handleUpload"
            />
          </div>
          <p v-if="isScanning && scanJob" class="scan-hint">
            {{
              scanJob.status === 'pending'
                ? t('metadata.scanningLibrary')
                : t('metadata.scanProgress', {
                    processed: scanJob.tracks_processed,
                    found: scanJob.tracks_found,
                  })
            }}
          </p>
          <p v-else-if="isBatchMatching && matchJob" class="scan-hint">
            {{
              matchJob.status === 'pending'
                ? t('metadata.organizing')
                : t('metadata.batchMatchProgress', {
                    processed: matchJob.tracks_processed,
                    total: matchJob.tracks_total,
                    auto: matchJob.auto_applied,
                    review: matchJob.needs_review,
                    unmatched: matchJob.unmatched,
                    failed: matchJob.failed,
                  })
            }}
          </p>
        </div>

        <div class="sidebar-card">
          <h3>{{ t('metadata.queue') }} ({{ queueTotal }})</h3>
          <div v-if="loadingQueue" class="queue-empty">{{ t('library.loading') }}</div>
          <div v-else-if="queue.length === 0" class="queue-empty">{{ t('metadata.emptyQueue') }}</div>
          <div v-else class="queue-list">
            <div
              v-for="item in queue"
              :key="item.id"
              class="queue-item"
              :class="{ active: selectedId === item.id }"
            >
              <button
                type="button"
                class="queue-select"
                @click="selectTrack(item)"
              >
                <div class="queue-thumb">
                  <img
                    :src="trackCoverSrc(item.id, item.updated_at, 'file')"
                    :alt="queueTitle(item)"
                    @error="hideBrokenCover"
                  />
                  <div class="thumb-placeholder">♪</div>
                </div>
                <div class="queue-info">
                  <p class="queue-title">{{ queueTitle(item) }}</p>
                  <p class="queue-sub">
                    {{ queueArtist(item) || t('metadata.unknownArtist') }}
                  </p>
                </div>
              </button>
              <button
                type="button"
                class="queue-delete"
                :title="t('metadata.delete')"
                :aria-label="t('metadata.delete')"
                :disabled="deleting || workspaceBusy"
                @click="openDeleteTrack(item, $event)"
              >
                <svg fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
                  <path
                    stroke-linecap="round"
                    stroke-linejoin="round"
                    stroke-width="2"
                    d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6M9 7V4a1 1 0 011-1h4a1 1 0 011 1v3m-7 0h8"
                  />
                </svg>
              </button>
            </div>
          </div>
          <div v-if="queueTotalPages > 1" class="queue-pager">
            <button
              class="ghost-btn"
              type="button"
              :disabled="queuePage <= 1 || loadingQueue"
              @click="goQueuePage(queuePage - 1)"
            >
              {{ t('metadata.previousPage') }}
            </button>
            <span class="queue-page-label">
              {{ t('metadata.queuePage', { page: queuePage, totalPages: queueTotalPages }) }}
            </span>
            <button
              class="ghost-btn"
              type="button"
              :disabled="queuePage >= queueTotalPages || loadingQueue"
              @click="goQueuePage(queuePage + 1)"
            >
              {{ t('metadata.nextPage') }}
            </button>
          </div>
        </div>
      </div>

      <!-- Right column -->
      <div class="meta-main">
        <div v-if="error" class="banner error">{{ error }}</div>
        <div v-else-if="statusMessage" class="banner ok">{{ statusMessage }}</div>

        <section class="panel">
          <h3>{{ t('metadata.issues') }}</h3>
          <div class="issue-strip">
            <button
              v-for="option in ISSUE_OPTIONS"
              :key="option.value"
              class="issue-chip"
              :class="{ active: activeIssue === option.value }"
              @click="selectIssue(option.value)"
            >
              <span class="issue-dot" :class="option.dot"></span>
              <span>{{ t(option.labelKey) }}</span>
              <span class="issue-count">{{ issueCounts[option.value] }}</span>
            </button>
          </div>
          <p class="issues-hint">{{ t('metadata.rematchHint', { threshold: matchPercent }) }}</p>
        </section>

        <section class="panel workspace">
          <div class="provider-row">
            <select
              id="meta-provider"
              v-model="provider"
              class="provider-select"
              :aria-label="t('metadata.provider')"
              :disabled="workspaceBusy"
            >
              <option
                v-for="option in PROVIDERS"
                :key="option.value"
                :value="option.value"
              >
                {{ t(option.labelKey) }}
              </option>
            </select>
            <button
              class="query-btn"
              :disabled="!selectedTrack || workspaceBusy"
              @click="queryMetadata"
            >
              {{ matching ? t('metadata.matching') : t('metadata.query') }}
            </button>
          </div>

          <template v-if="selectedTrack">
            <h4>{{ t('metadata.currentMatch') }}</h4>
            <div class="current-item">
              <div class="current-cover">
                <img
                  :src="trackCoverSrc(selectedTrack.id, selectedTrack.updated_at, 'album')"
                  :alt="selectedTrack.title"
                  @error="hideBrokenCover"
                />
                <div class="cover-placeholder">♪</div>
              </div>
              <div class="current-info">
                <h5>{{ selectedTrack.title }}</h5>
                <p>
                  {{ trackArtistLabel(selectedTrack) || t('metadata.unknownArtist') }}
                  ·
                  {{ selectedTrack.album?.title || t('metadata.unknownAlbum') }}
                  ·
                  {{ formatDuration(selectedTrack.duration_ms) }}
                </p>
                <p class="file-path" :title="selectedTrack.file_path">
                  {{ t('metadata.localFile') }}: {{ selectedTrack.file_path }}
                </p>
              </div>
            </div>

            <h4 class="section-title">{{ t('metadata.candidates') }}</h4>
            <div v-if="matching" class="candidates-empty">{{ t('metadata.matching') }}</div>
            <div v-else-if="candidates.length === 0" class="candidates-empty">
              {{ t('metadata.noCandidatesHint') }}
            </div>
            <div v-else class="candidates">
              <button
                v-for="candidate in candidates"
                :key="`${candidate.provider}-${candidate.mbid}`"
                class="candidate-card"
                @click="openCandidate(candidate)"
              >
                <div class="candidate-cover">
                  <img
                    v-if="candidate.cover_url"
                    :src="candidate.cover_url"
                    :alt="candidate.title"
                    loading="lazy"
                    referrerpolicy="no-referrer"
                  />
                  <div v-else class="cover-placeholder">♪</div>
                </div>
                <div class="candidate-body">
                  <h6>{{ candidate.title }}</h6>
                  <p>
                    {{ formatArtistName(candidate.artist) || candidate.artist }}
                    · {{ candidate.album }}
                    <template v-if="candidate.year"> · {{ candidate.year }}</template>
                  </p>
                  <div class="candidate-meta">
                    <span class="candidate-source">{{ providerLabel(candidate.provider) }}</span>
                    <span class="candidate-score">{{ scorePercent(candidate) }}%</span>
                  </div>
                </div>
              </button>
            </div>
          </template>

          <div v-else class="candidates-empty">{{ t('metadata.selectTrackHint') }}</div>
        </section>
      </div>
    </div>

    <div
      v-if="editorOpen"
      class="editor-backdrop"
      @click.self="closeEditor"
    >
      <div class="editor-modal" role="dialog" aria-modal="true">
        <div class="editor-header">
          <h3>{{ t('metadata.editTitle') }}</h3>
          <button class="editor-close" type="button" @click="closeEditor">×</button>
        </div>

        <div class="editor-body" :class="{ 'no-cover': !editForm.cover_url }">
          <div v-if="editForm.cover_url" class="editor-cover">
            <img :src="editForm.cover_url" :alt="editForm.title" />
          </div>
          <div class="editor-fields">
            <label>
              <span>{{ t('metadata.fieldTitle') }}</span>
              <input v-model="editForm.title" type="text" />
            </label>
            <label>
              <span>{{ t('metadata.fieldArtist') }}</span>
              <input v-model="editForm.artist" type="text" />
            </label>
            <label>
              <span>{{ t('metadata.fieldAlbum') }}</span>
              <input v-model="editForm.album" type="text" />
            </label>
            <label>
              <span>{{ t('metadata.fieldYear') }}</span>
              <input v-model="editForm.year" type="text" inputmode="numeric" />
            </label>
            <p v-if="editForm.score" class="editor-meta">
              {{ t('metadata.fieldScore') }}: {{ editForm.score }}%
            </p>
          </div>
        </div>

        <div class="editor-footer">
          <button class="ghost-btn" type="button" :disabled="saving" @click="closeEditor">
            {{ t('metadata.cancel') }}
          </button>
          <button class="query-btn" type="button" :disabled="saving" @click="saveEditedMetadata">
            {{ saving ? t('metadata.saving') : t('metadata.save') }}
          </button>
        </div>
      </div>
    </div>

    <div
      v-if="pendingDelete"
      class="confirm-backdrop"
      @click.self="closeDeleteConfirm"
    >
      <div class="confirm-modal" role="dialog" aria-modal="true">
        <div class="confirm-header">
          <h3>{{ t('metadata.deleteTrack') }}</h3>
          <button
            type="button"
            class="confirm-close"
            :disabled="deleting"
            @click="closeDeleteConfirm"
          >
            ×
          </button>
        </div>
        <div class="confirm-body">
          <p>{{ t('metadata.deleteTrackConfirm', { title: pendingDelete.title }) }}</p>
          <p v-if="deleteError" class="confirm-error">{{ deleteError }}</p>
        </div>
        <div class="confirm-footer">
          <button
            type="button"
            class="ghost-btn"
            :disabled="deleting"
            @click="closeDeleteConfirm"
          >
            {{ t('metadata.cancel') }}
          </button>
          <button
            type="button"
            class="danger-btn"
            :disabled="deleting"
            @click="confirmDeleteTrack"
          >
            {{ deleting ? t('metadata.deleting') : t('metadata.delete') }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.main-wrapper {
  padding: 24px 32px;
  max-width: 1400px;
  margin: 0 auto;
}

.meta-layout {
  display: grid;
  grid-template-columns: 280px 1fr;
  gap: 24px;
}

.sidebar-card {
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-card);
  padding: 16px;
  margin-bottom: 16px;
}

.sidebar-card h3 {
  font-size: 14px;
  font-weight: var(--font-weight-semibold);
  color: var(--color-text);
  margin-bottom: 14px;
}

.issue-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  flex-shrink: 0;
}

.issue-dot.yellow { background: #fbbf24; }
.issue-dot.red { background: #ef4444; }
.issue-dot.blue { background: #3b82f6; }
.issue-dot.indigo { background: #6366f1; }
.issue-dot.purple { background: #8b5cf6; }
.issue-dot.gray { background: #94a3b8; }

.issue-strip {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.issue-chip {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-control);
  background: var(--color-bg);
  color: var(--color-text);
  font-size: 12px;
  font-weight: var(--font-weight-regular);
  cursor: pointer;
  transition: background-color var(--motion-duration) var(--motion-ease),
              border-color var(--motion-duration) var(--motion-ease),
              color var(--motion-duration) var(--motion-ease);
}

.issue-chip:hover {
  color: var(--color-text);
  border-color: var(--color-accent);
}

.issue-chip.active {
  border-color: var(--color-accent);
  color: var(--color-text);
  background: rgba(99, 102, 241, .08);
}

.issue-chip .issue-count {
  font-weight: var(--font-weight-semibold);
  color: var(--color-text);
}

.issues-hint {
  font-size: 11px;
  color: var(--color-text-muted);
  margin-top: 12px;
  margin-bottom: 0;
  line-height: 1.4;
}

.provider-row {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px;
  margin-bottom: 16px;
  padding-bottom: 16px;
  border-bottom: 1px solid var(--color-border);
}

.provider-select {
  width: 132px;
  padding: 6px 10px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-control);
  background: var(--color-bg);
  color: var(--color-text);
  font-size: 13px;
}

.provider-select:disabled {
  opacity: 0.6;
}

.panel {
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-card);
  padding: 16px 20px;
  margin-bottom: 16px;
}

.panel > h3 {
  font-size: 14px;
  font-weight: var(--font-weight-semibold);
  color: var(--color-text);
  margin: 0 0 14px;
}

.workspace {
  min-height: 360px;
}

.workspace h4 {
  font-size: 13px;
  font-weight: var(--font-weight-medium);
  color: var(--color-text);
  margin-bottom: 16px;
}

.section-title {
  margin-top: 20px;
}

.banner {
  margin-bottom: 16px;
  padding: 10px 12px;
  border-radius: var(--radius-control);
  font-size: 13px;
}

.banner.error {
  background: rgba(239, 68, 68, .1);
  border: 1px solid #ef4444;
}

.banner.ok {
  background: rgba(34, 197, 94, .1);
  border: 1px solid rgba(34, 197, 94, .35);
}

.quick-actions {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 8px;
}

.upload-input {
  display: none;
}

.quick-btn {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 14px 8px;
  background: var(--color-bg);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-control);
  color: var(--color-text);
  font-size: 12px;
  font-weight: var(--font-weight-medium);
  transition: all var(--motion-duration) var(--motion-ease);
}

.quick-btn:hover:not(:disabled) {
  background: var(--color-border);
  color: var(--color-text);
  border-color: var(--color-accent);
}

.quick-btn:disabled {
  opacity: .45;
  cursor: not-allowed;
}

.quick-btn svg {
  width: 18px;
  height: 18px;
}

.scan-hint {
  margin-top: 10px;
  font-size: 11px;
  color: var(--color-text-muted);
  text-align: center;
}

.queue-list {
  border: 1px solid var(--color-border);
  border-radius: var(--radius-card);
  overflow: hidden;
  max-height: 480px;
  overflow-y: auto;
}

.queue-pager {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-top: 10px;
}

.queue-page-label {
  font-size: 11px;
  color: var(--color-text-muted);
  text-align: center;
  flex: 1;
}

.queue-empty,
.candidates-empty {
  font-size: 12px;
  color: var(--color-text-muted);
  padding: 16px 4px;
  text-align: center;
}

.queue-item {
  display: flex;
  align-items: center;
  gap: 4px;
  width: 100%;
  padding: 4px 6px 4px 4px;
  border-bottom: 1px solid var(--color-border);
  background: transparent;
  color: inherit;
  transition: background-color var(--motion-duration) var(--motion-ease);
}

.queue-item:last-child {
  border-bottom: none;
}

.queue-item:hover,
.queue-item.active {
  background: var(--color-bg);
}

.queue-select {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
  flex: 1;
  padding: 6px 6px 6px 8px;
  border: none;
  background: transparent;
  color: inherit;
  text-align: left;
  cursor: pointer;
}

.queue-delete {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  flex-shrink: 0;
  border: none;
  border-radius: var(--radius-control);
  background: transparent;
  color: var(--color-text-muted);
  cursor: pointer;
  transition:
    color var(--motion-duration) var(--motion-ease),
    background-color var(--motion-duration) var(--motion-ease);
}

.queue-delete svg {
  width: 15px;
  height: 15px;
}

.queue-delete:hover:not(:disabled) {
  color: #dc2626;
  background: color-mix(in srgb, #dc2626 12%, transparent);
}

.queue-delete:disabled {
  opacity: 0.4;
  cursor: default;
}

.queue-thumb {
  position: relative;
  width: 32px;
  height: 32px;
  border-radius: 4px;
  background: var(--color-surface);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  overflow: hidden;
}

.queue-thumb img,
.current-cover img {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  object-fit: cover;
  z-index: 1;
}

.thumb-placeholder,
.cover-placeholder {
  font-size: 12px;
  color: var(--color-text-muted);
}

.queue-info {
  flex: 1;
  min-width: 0;
}

.queue-title {
  font-size: 12px;
  font-weight: var(--font-weight-medium);
  color: var(--color-text);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.queue-sub {
  font-size: 11px;
  font-weight: var(--font-weight-regular);
  color: var(--color-text-muted);
}

.query-btn {
  flex-shrink: 0;
  border: none;
  border-radius: var(--radius-control);
  padding: 6px 14px;
  font-size: 12px;
  background: var(--color-accent);
  color: #fff;
}

.query-btn:disabled {
  opacity: .5;
  cursor: not-allowed;
}

.current-item {
  display: flex;
  gap: 16px;
  margin-bottom: 20px;
  padding-bottom: 16px;
  border-bottom: 1px solid var(--color-border);
}

.current-cover {
  position: relative;
  width: 80px;
  height: 80px;
  border-radius: var(--radius-control);
  background: var(--color-bg);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  overflow: hidden;
}

.current-info {
  min-width: 0;
  flex: 1;
}

.current-info h5 {
  font-size: 15px;
  font-weight: var(--font-weight-semibold);
  margin-bottom: 4px;
}

.current-info p {
  font-size: 12px;
  color: var(--color-text-muted);
  margin-bottom: 8px;
}

.file-path {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  font-family: ui-monospace, monospace;
}

.ghost-btn {
  border-radius: var(--radius-control);
  padding: 6px 12px;
  font-size: 12px;
  background: var(--color-bg);
  border: 1px solid var(--color-border);
  color: var(--color-text);
}

.ghost-btn:disabled {
  opacity: .5;
  cursor: not-allowed;
}

.candidates {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 12px;
}

.candidate-card {
  display: flex;
  gap: 12px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-control);
  padding: 12px;
  background: var(--color-bg);
  color: inherit;
  text-align: left;
  cursor: pointer;
  transition: all var(--motion-duration) var(--motion-ease);
}

.candidate-card:hover {
  border-color: var(--color-accent);
}

.candidate-card.selected {
  border-color: var(--color-accent);
  background: rgba(99, 102, 241, 0.1);
}

.candidate-cover {
  width: 64px;
  height: 64px;
  border-radius: var(--radius-control);
  background: var(--color-surface);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  overflow: hidden;
}

.candidate-cover img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.candidate-body {
  min-width: 0;
  flex: 1;
}

.candidate-card h6 {
  font-size: 13px;
  font-weight: var(--font-weight-medium);
  margin-bottom: 4px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.candidate-card p {
  font-size: 11px;
  color: var(--color-text-muted);
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.candidate-meta {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 6px;
}

.candidate-source {
  padding: 2px 8px;
  border: 1px solid var(--color-border);
  border-radius: 999px;
  font-size: 11px;
  color: var(--color-text-muted);
}

.candidate-score {
  display: inline-block;
  padding: 2px 8px;
  background: var(--color-accent);
  color: #fff;
  border-radius: 999px;
  font-size: 11px;
}

.editor-backdrop {
  position: fixed;
  inset: 0;
  z-index: 40;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  background: rgba(15, 23, 42, .45);
}

.editor-modal {
  width: min(520px, 100%);
  max-height: min(90vh, 720px);
  overflow: auto;
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-card);
  box-shadow: 0 18px 48px rgba(15, 23, 42, .18);
}

.editor-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 16px 20px;
  border-bottom: 1px solid var(--color-border);
}

.editor-header h3 {
  margin: 0;
  font-size: 15px;
}

.editor-close {
  border: none;
  background: transparent;
  color: var(--color-text-muted);
  font-size: 22px;
  line-height: 1;
  padding: 0 4px;
}

.editor-body {
  display: grid;
  grid-template-columns: 96px 1fr;
  gap: 16px;
  padding: 20px;
}

.editor-body.no-cover {
  grid-template-columns: 1fr;
}

.editor-cover {
  width: 96px;
  height: 96px;
  border-radius: var(--radius-control);
  overflow: hidden;
  background: var(--color-bg);
}

.editor-cover img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.editor-fields {
  display: flex;
  flex-direction: column;
  gap: 12px;
  min-width: 0;
}

.editor-fields label {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 12px;
  color: var(--color-text-muted);
}

.editor-fields input {
  padding: 8px 10px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-control);
  background: var(--color-bg);
  color: var(--color-text);
  font-size: 13px;
}

.editor-meta {
  margin: 0;
  font-size: 12px;
  color: var(--color-text-muted);
}

.editor-footer {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  padding: 16px 20px;
  border-top: 1px solid var(--color-border);
}

.confirm-backdrop {
  position: fixed;
  inset: 0;
  z-index: 50;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  background: rgba(15, 23, 42, .45);
}

.confirm-modal {
  width: min(420px, 100%);
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-card);
  box-shadow: 0 18px 48px rgba(15, 23, 42, .18);
}

.confirm-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 16px 20px;
  border-bottom: 1px solid var(--color-border);
}

.confirm-header h3 {
  margin: 0;
  font-size: 15px;
}

.confirm-close {
  border: none;
  background: transparent;
  color: var(--color-text-muted);
  font-size: 22px;
  line-height: 1;
  padding: 0 4px;
  cursor: pointer;
}

.confirm-body {
  padding: 16px 20px;
}

.confirm-body p {
  margin: 0;
  font-size: 13px;
  line-height: 1.6;
  color: var(--color-text);
}

.confirm-error {
  margin-top: 10px !important;
  color: #dc2626 !important;
}

.confirm-footer {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  padding: 12px 20px 16px;
  border-top: 1px solid var(--color-border);
}

.danger-btn {
  padding: 6px 14px;
  border: 1px solid #dc2626;
  border-radius: var(--radius-control);
  background: #dc2626;
  color: #fff;
  font-size: 13px;
  cursor: pointer;
}

.danger-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

@media (max-width: 900px) {
  .meta-layout {
    grid-template-columns: 1fr;
  }

  .editor-body {
    grid-template-columns: 1fr;
  }
}
</style>
