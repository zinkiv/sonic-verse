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
import { parseArtistChipInput, trackArtistLabel } from '@/utils/artists'

const { t } = useI18n()
const route = useRoute()
const router = useRouter()
const libraryStore = useLibraryStore()

type IssueFilter = MetadataIssue
type LibraryIssueFilter = Exclude<IssueFilter, 'transfer' | 'all'>

const PROVIDERS: { value: MetadataProvider; labelKey: string }[] = [
  { value: 'qqmusic', labelKey: 'metadata.providerQq' },
  { value: 'netease', labelKey: 'metadata.providerNetease' },
]

const ISSUE_OPTIONS: { value: LibraryIssueFilter; labelKey: string; dot: string }[] = [
  { value: 'missing_album', labelKey: 'metadata.missingAlbums', dot: 'purple' },
  { value: 'missing_cover', labelKey: 'metadata.missingCovers', dot: 'yellow' },
  { value: 'unknown_artist', labelKey: 'metadata.unknownArtists', dot: 'red' },
]

const VALID_ISSUES: IssueFilter[] = ['transfer', ...ISSUE_OPTIONS.map((option) => option.value)]

const activeIssue = ref<IssueFilter>('transfer')
const provider = ref<MetadataProvider>('qqmusic')
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
const coverFile = ref<File | null>(null)
const coverObjectUrl = ref<string | null>(null)
const coverInput = ref<HTMLInputElement | null>(null)
/** Selected tile id: file | match:<url> | upload */
const selectedCoverId = ref<string | null>(null)
/** True when user explicitly cleared cover; save sends cover_source=none. */
const coverCleared = ref(false)
const filenameTouched = ref(false)
const editArtists = ref<string[]>([])
const artistDraft = ref('')
const albumArtistChoice = ref('')
const ALBUM_ARTIST_ALL = '__all__'
const editForm = ref({
  title: '',
  filename: '',
  artist: '',
  album: '',
  album_artist: '',
  year: '' as string,
  mbid: '',
  album_mbid: '' as string,
  duration: 0,
  cover_url: null as string | null,
  artist_image_url: null as string | null,
  artist_images: null as { name: string; url: string }[] | null,
  provider: 'qqmusic' as MetadataProvider,
  score: 0,
})

type CoverOption = {
  id: string
  kind: 'file' | 'match' | 'upload'
  src: string
  remoteUrl?: string
}

type DisplayCandidate = MatchCandidate & {
  origin: 'file' | 'provider'
}

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
let candidatesEpoch = 0

const selectedTrack = computed(
  () => queue.value.find((track) => track.id === selectedId.value) ?? null
)

const coverOptions = computed((): CoverOption[] => {
  const options: CoverOption[] = []
  const seen = new Set<string>()
  const track = selectedTrack.value

  if (track?.file_tags?.has_cover) {
    const src = trackCoverSrc(track.id, track.updated_at, 'file')
    options.push({ id: 'file', kind: 'file', src })
    seen.add(src)
  }

  for (const candidate of candidates.value) {
    const url = (candidate.cover_url || '').trim()
    if (!url || seen.has(url)) continue
    seen.add(url)
    options.push({ id: `match:${url}`, kind: 'match', src: url, remoteUrl: url })
  }

  if (coverObjectUrl.value) {
    options.push({ id: 'upload', kind: 'upload', src: coverObjectUrl.value })
  }

  return options
})

const selectedCover = computed(
  () => coverOptions.value.find((item) => item.id === selectedCoverId.value) ?? null
)

const editorCoverSrc = computed(() => selectedCover.value?.src ?? null)

const albumArtistOptions = computed(() => {
  const names = editArtists.value
  const options = names.map((name) => ({ value: name, label: name }))
  if (names.length > 1) {
    const allLabel = names.join(',')
    options.push({
      value: ALBUM_ARTIST_ALL,
      label: allLabel,
    })
  }
  return options
})

const displayCandidates = computed((): DisplayCandidate[] => {
  const track = selectedTrack.value
  const items: DisplayCandidate[] = []
  if (track) {
    const tags = track.file_tags
    const title = (tags?.title || track.title || '').trim()
    const artist = (
      (tags?.artist || '').trim() ||
      trackArtistLabel(track) ||
      ''
    ).trim()
    const album = (tags?.album || track.album?.title || '').trim()
    items.push({
      origin: 'file',
      title: title || track.title,
      artist: artist || t('metadata.unknownArtist'),
      album,
      duration: track.duration_ms ? Math.round(track.duration_ms / 1000) : 0,
      mbid: `file:${track.id}`,
      album_mbid: null,
      year: track.album?.year ?? null,
      confidence: 0,
      score: 0,
      cover_url: tags?.has_cover
        ? trackCoverSrc(track.id, track.updated_at, 'file')
        : null,
      artist_image_url: null,
      artist_images: null,
      provider: null,
    })
  }
  for (const candidate of candidates.value) {
    items.push({ ...candidate, origin: 'provider' })
  }
  return items
})

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
      const keepId = selectedId.value
      activeIssue.value = 'transfer'
      queuePage.value = 1
      await loadQueue(keepId)
      if (keepId) {
        await ensureTrackInQueue(keepId)
      }
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
      const keepId = selectedId.value
      activeIssue.value = 'transfer'
      queuePage.value = 1
      await loadQueue(keepId)
      if (keepId) {
        await ensureTrackInQueue(keepId)
        await loadStoredCandidates(keepId)
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

function isTransferTrack(track: Track | null | undefined): boolean {
  if (!track?.file_path) return false
  const path = track.file_path.replace(/\\/g, '/')
  const root = (transferPath.value || '').replace(/\\/g, '/').replace(/\/+$/, '')
  if (root) {
    return path === root || path.startsWith(`${root}/`)
  }
  return (
    path === '/transfer' ||
    path.startsWith('/transfer/') ||
    path.includes('/data/transfer/')
  )
}

async function ensureTrackInQueue(trackId: string): Promise<boolean> {
  if (queue.value.some((item) => item.id === trackId)) {
    selectedId.value = trackId
    return true
  }
  try {
    const track = await api.get<Track>(`/tracks/${trackId}`)
    queue.value = [track, ...queue.value.filter((item) => item.id !== trackId)]
    selectedId.value = track.id
    return true
  } catch {
    return false
  }
}

async function refreshTrackInQueue(trackId: string) {
  try {
    const track = await api.get<Track>(`/tracks/${trackId}`)
    const exists = queue.value.some((item) => item.id === trackId)
    queue.value = exists
      ? queue.value.map((item) => (item.id === trackId ? track : item))
      : [track, ...queue.value]
    selectedId.value = track.id
  } catch {
    await loadQueue(null)
  }
}

async function bootstrapMetadataPage(preferId?: string | null) {
  await libraryStore.fetchStats()
  const scanStarted = await syncTransferFromDisk()
  if (scanStarted && !preferId) return

  if (!scanStarted) {
    await loadQueue(preferId ?? null)
  }

  if (preferId) {
    await ensureTrackInQueue(preferId)
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
  const epoch = ++candidatesEpoch
  try {
    const data = await api.get<MatchCandidatesResponse>(`/tracks/${trackId}/candidates`)
    if (epoch !== candidatesEpoch || selectedId.value !== trackId || matching.value) return
    candidates.value = data.candidates
  } catch {
    if (epoch !== candidatesEpoch || selectedId.value !== trackId || matching.value) return
    candidates.value = []
  }
}

async function runMatch(trackId: string) {
  matching.value = true
  error.value = null
  statusMessage.value = null
  candidates.value = []
  closeEditor()
  const epoch = ++candidatesEpoch

  try {
    const data = await api.post<MatchCandidatesResponse>(`/tracks/${trackId}/match`, {
      provider: provider.value,
    })
    if (epoch !== candidatesEpoch || selectedId.value !== trackId) return
    candidates.value = data.candidates
    if (data.candidates.length === 0) {
      statusMessage.value = t('metadata.noCandidatesHint')
    }
  } catch (err) {
    if (epoch !== candidatesEpoch || selectedId.value !== trackId) return
    error.value = err instanceof Error ? err.message : t('metadata.matchFailed')
  } finally {
    if (epoch === candidatesEpoch) {
      matching.value = false
    }
  }
}

function sanitizeFilenamePart(value: string): string {
  return value
    .replace(/[<>:"/\\|?*]/g, '_')
    .replace(/\.+$/g, '')
    .trim()
}

function trackExtension(track: Track | null | undefined): string {
  if (!track?.file_path) return '.flac'
  const name = track.file_path.split(/[/\\]/).pop() || ''
  const dot = name.lastIndexOf('.')
  return dot >= 0 ? name.slice(dot) : '.flac'
}

function defaultLibraryFilename(artist: string, title: string, ext: string): string {
  const artistPart = sanitizeFilenamePart(artist) || 'Unknown Artist'
  const titlePart = sanitizeFilenamePart(title) || 'Unknown Track'
  const suffix = ext.startsWith('.') ? ext : `.${ext}`
  return `${artistPart}-${titlePart}${suffix}`
}

function syncFilenameFromFields() {
  if (filenameTouched.value) return
  editForm.value.filename = defaultLibraryFilename(
    editArtists.value.join(',') || editForm.value.artist,
    editForm.value.title,
    trackExtension(selectedTrack.value)
  )
}

function onFilenameInput() {
  filenameTouched.value = true
}

function onTitleOrArtistInput() {
  syncFilenameFromFields()
}

function syncArtistsToForm() {
  editForm.value.artist = editArtists.value.join(',')
  if (
    albumArtistChoice.value &&
    albumArtistChoice.value !== ALBUM_ARTIST_ALL &&
    !editArtists.value.includes(albumArtistChoice.value)
  ) {
    albumArtistChoice.value =
      editArtists.value.length > 1 ? ALBUM_ARTIST_ALL : editArtists.value[0] || ''
  } else if (!albumArtistChoice.value && editArtists.value.length === 1) {
    albumArtistChoice.value = editArtists.value[0]
  } else if (editArtists.value.length <= 1 && albumArtistChoice.value === ALBUM_ARTIST_ALL) {
    albumArtistChoice.value = editArtists.value[0] || ''
  }
  editForm.value.album_artist = resolveAlbumArtist()
  syncFilenameFromFields()
}

function resolveAlbumArtist(): string {
  if (!editArtists.value.length) return ''
  if (albumArtistChoice.value === ALBUM_ARTIST_ALL || !albumArtistChoice.value) {
    return editArtists.value.join(',')
  }
  return albumArtistChoice.value
}

function setEditArtistsFromRaw(raw: string) {
  editArtists.value = parseArtistChipInput(raw)
  artistDraft.value = ''
  albumArtistChoice.value =
    editArtists.value.length > 1 ? ALBUM_ARTIST_ALL : editArtists.value[0] || ''
  syncArtistsToForm()
}

function removeEditArtist(index: number) {
  if (saving.value) return
  editArtists.value = editArtists.value.filter((_, i) => i !== index)
  syncArtistsToForm()
}

function clearEditArtists() {
  if (saving.value) return
  editArtists.value = []
  albumArtistChoice.value = ''
  syncArtistsToForm()
}

function commitArtistDraft() {
  const name = artistDraft.value.trim()
  if (!name) return
  const key = name.toLocaleLowerCase()
  if (!editArtists.value.some((item) => item.toLocaleLowerCase() === key)) {
    editArtists.value = [...editArtists.value, name]
  }
  artistDraft.value = ''
  if (editArtists.value.length > 1 && !albumArtistChoice.value) {
    albumArtistChoice.value = ALBUM_ARTIST_ALL
  }
  syncArtistsToForm()
}

function editArtistChip(index: number) {
  if (saving.value) return
  const name = editArtists.value[index]
  editArtists.value = editArtists.value.filter((_, i) => i !== index)
  artistDraft.value = name
  syncArtistsToForm()
}

function onArtistDraftKeydown(event: KeyboardEvent) {
  if (event.isComposing) return
  if (event.key === 'Enter') {
    event.preventDefault()
    commitArtistDraft()
  } else if (event.key === 'Backspace' && !artistDraft.value && editArtists.value.length) {
    removeEditArtist(editArtists.value.length - 1)
  }
}

function onAlbumArtistChange() {
  editForm.value.album_artist = resolveAlbumArtist()
}

function queryMetadata() {
  if (!selectedTrack.value || workspaceBusy.value) return
  void runMatch(selectedTrack.value.id)
}

function openCandidate(candidate: DisplayCandidate) {
  revokeCoverObjectUrl()
  coverFile.value = null
  coverCleared.value = false
  filenameTouched.value = false
  const fromFile = candidate.origin === 'file'
  const artist = (candidate.artist || '').trim()
  const title = candidate.title
  setEditArtistsFromRaw(artist)
  editForm.value = {
    ...editForm.value,
    title,
    filename: defaultLibraryFilename(
      editArtists.value.join(',') || artist,
      title,
      trackExtension(selectedTrack.value)
    ),
    artist: editArtists.value.join(',') || artist,
    album: candidate.album,
    album_artist: resolveAlbumArtist(),
    year: candidate.year != null ? String(candidate.year) : '',
    mbid: fromFile ? '' : candidate.mbid,
    album_mbid: fromFile ? '' : candidate.album_mbid ?? '',
    duration: candidate.duration || 0,
    cover_url: fromFile ? null : candidate.cover_url ?? null,
    artist_image_url: fromFile ? null : candidate.artist_image_url ?? null,
    artist_images: fromFile ? null : candidate.artist_images ?? null,
    provider: candidate.provider || provider.value,
    score: fromFile ? 0 : scorePercent(candidate),
  }
  editorOpen.value = true
  if (fromFile) {
    selectedCoverId.value = selectedTrack.value?.file_tags?.has_cover ? 'file' : null
  } else {
    const matchUrl = (candidate.cover_url || '').trim()
    if (matchUrl) {
      selectedCoverId.value = `match:${matchUrl}`
    } else if (selectedTrack.value?.file_tags?.has_cover) {
      selectedCoverId.value = 'file'
    } else {
      selectedCoverId.value = null
    }
  }
}

function revokeCoverObjectUrl() {
  if (coverObjectUrl.value) {
    URL.revokeObjectURL(coverObjectUrl.value)
    coverObjectUrl.value = null
  }
}

function selectCoverOption(option: CoverOption) {
  if (saving.value) return
  coverCleared.value = false
  selectedCoverId.value = option.id
  editForm.value.cover_url = option.kind === 'match' ? option.remoteUrl ?? null : null
}

function clearSelectedCover(event?: Event) {
  event?.stopPropagation()
  if (saving.value) return
  revokeCoverObjectUrl()
  coverFile.value = null
  selectedCoverId.value = null
  editForm.value.cover_url = null
  coverCleared.value = true
}

function pickCoverFile() {
  if (saving.value) return
  coverInput.value?.click()
}

function onCoverFileSelected(event: Event) {
  const input = event.target as HTMLInputElement | null
  const file = input?.files?.[0]
  if (input) input.value = ''
  if (!file || !file.type.startsWith('image/')) return
  revokeCoverObjectUrl()
  coverFile.value = file
  coverObjectUrl.value = URL.createObjectURL(file)
  selectedCoverId.value = 'upload'
  editForm.value.cover_url = coverObjectUrl.value
  coverCleared.value = false
}

function closeEditor() {
  editorOpen.value = false
  revokeCoverObjectUrl()
  coverFile.value = null
  selectedCoverId.value = null
  coverCleared.value = false
  filenameTouched.value = false
  editArtists.value = []
  artistDraft.value = ''
  albumArtistChoice.value = ''
}

async function saveEditedMetadata() {
  const track = selectedTrack.value
  if (!track || saving.value) return

  const title = editForm.value.title.trim()
  commitArtistDraft()
  const artist = editArtists.value.join(',').trim()
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
    const formData = new FormData()
    formData.append('title', title)
    formData.append('artist', artist)
    formData.append('artist_names', JSON.stringify(editArtists.value))
    formData.append('album', album || title)
    const albumArtist = resolveAlbumArtist().trim()
    if (albumArtist) {
      formData.append('album_artist', albumArtist)
    }
    const filename = editForm.value.filename.trim()
    if (filename) {
      formData.append('filename', filename)
    }
    if (yearRaw && Number.isFinite(year)) {
      formData.append('year', String(year))
    }
    if (editForm.value.mbid) {
      formData.append('mbid', editForm.value.mbid)
    }
    if (editForm.value.album_mbid) {
      formData.append('album_mbid', editForm.value.album_mbid)
    }
    if (editForm.value.duration) {
      formData.append('duration', String(editForm.value.duration))
    }
    formData.append('provider', editForm.value.provider)

    if ((editForm.value.artist_image_url || '').trim()) {
      formData.append('artist_image_url', editForm.value.artist_image_url!.trim())
    }
    if (editForm.value.artist_images?.length) {
      formData.append('artist_images', JSON.stringify(editForm.value.artist_images))
    }

    const cover = selectedCover.value
    if (coverCleared.value && !cover) {
      formData.append('cover_source', 'none')
    } else if (cover?.kind === 'file') {
      formData.append('cover_source', 'file')
    } else if (cover?.kind === 'match' && cover.remoteUrl) {
      formData.append('cover_source', 'match')
      formData.append('cover_url', cover.remoteUrl)
    } else if (cover?.kind === 'upload' && coverFile.value) {
      formData.append('cover_source', 'upload')
      formData.append('cover', coverFile.value)
    }

    await api.upload<Track>(`/tracks/${track.id}/manual-save`, formData)
    const savedId = track.id
    const importedFromTransfer = isTransferTrack(track)
    closeEditor()
    statusMessage.value = importedFromTransfer
      ? t('metadata.saveImported')
      : t('metadata.saveSuccess')
    await libraryStore.fetchStats()
    if (importedFromTransfer) {
      await loadQueue(null)
    } else {
      await refreshTrackInQueue(savedId)
      await loadStoredCandidates(savedId)
    }
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

function onCoverError(event: Event) {
  const img = event.target as HTMLImageElement | null
  if (img) img.style.display = 'none'
}

function onCoverLoad(event: Event) {
  const img = event.target as HTMLImageElement | null
  if (img) img.style.display = ''
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

  if (autoMatch && queryTrackId && selectedId.value === queryTrackId) {
    await runMatch(queryTrackId)
  }

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
  revokeCoverObjectUrl()
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
                    @error="onCoverError"
                    @load="onCoverLoad"
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
                  :key="selectedTrack.id"
                  :src="trackCoverSrc(selectedTrack.id, selectedTrack.updated_at, 'file')"
                  :alt="selectedTrack.title"
                  @error="onCoverError"
                  @load="onCoverLoad"
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
            <div v-else class="candidates">
              <button
                v-for="candidate in displayCandidates"
                :key="
                  candidate.origin === 'file'
                    ? `file-${selectedTrack?.id}`
                    : `${candidate.provider}-${candidate.mbid}`
                "
                class="candidate-card"
                :class="{ 'is-file': candidate.origin === 'file' }"
                @click="openCandidate(candidate)"
              >
                <div class="candidate-cover">
                  <img
                    v-if="candidate.cover_url"
                    :src="candidate.cover_url"
                    :alt="candidate.title"
                    loading="lazy"
                    :referrerpolicy="candidate.origin === 'provider' ? 'no-referrer' : undefined"
                    @error="onCoverError"
                    @load="onCoverLoad"
                  />
                  <div v-else class="cover-placeholder">♪</div>
                </div>
                <div class="candidate-body">
                  <h6>{{ candidate.title }}</h6>
                  <p>
                    {{ candidate.artist || t('metadata.unknownArtist') }}
                    <template v-if="candidate.album"> · {{ candidate.album }}</template>
                    <template v-if="candidate.year"> · {{ candidate.year }}</template>
                  </p>
                  <div class="candidate-meta">
                    <span class="candidate-source">
                      {{
                        candidate.origin === 'file'
                          ? t('metadata.fileMetadata')
                          : providerLabel(candidate.provider)
                      }}
                    </span>
                    <span
                      v-if="candidate.origin === 'file'"
                      class="candidate-score file-edit"
                    >
                      {{ t('metadata.editAction') }}
                    </span>
                    <span v-else class="candidate-score">{{ scorePercent(candidate) }}%</span>
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

        <div class="editor-body">
          <div class="editor-cover-col">
            <div class="editor-cover" :class="{ empty: !editorCoverSrc }">
              <img v-if="editorCoverSrc" :src="editorCoverSrc" :alt="editForm.title" />
              <div v-else class="cover-placeholder editor-cover-hint">♪</div>
              <button
                v-if="editorCoverSrc"
                type="button"
                class="cover-clear"
                :disabled="saving"
                :title="t('metadata.clearCover')"
                @click="clearSelectedCover"
              >
                ×
              </button>
            </div>
            <div class="cover-picker">
              <div class="cover-picker-head">
                <span>{{ t('metadata.coverSelectTitle') }}</span>
                <span class="cover-picker-count">{{ coverOptions.length }}</span>
              </div>
              <div class="cover-grid">
                <button
                  v-for="option in coverOptions"
                  :key="option.id"
                  type="button"
                  class="cover-tile"
                  :class="{ active: selectedCoverId === option.id }"
                  :disabled="saving"
                  :title="
                    option.kind === 'file'
                      ? t('metadata.coverFromFile')
                      : option.kind === 'upload'
                        ? t('metadata.coverFromUpload')
                        : t('metadata.coverFromMatch')
                  "
                  @click="selectCoverOption(option)"
                >
                  <img
                    :src="option.src"
                    alt=""
                    :referrerpolicy="option.kind === 'match' ? 'no-referrer' : undefined"
                    @error="onCoverError"
                    @load="onCoverLoad"
                  />
                  <span
                    v-if="selectedCoverId === option.id"
                    class="cover-check"
                    aria-hidden="true"
                  >
                    ✓
                  </span>
                  <span
                    v-if="selectedCoverId === option.id"
                    class="cover-tile-clear"
                    role="button"
                    tabindex="0"
                    :title="t('metadata.clearCover')"
                    @click="clearSelectedCover"
                    @keydown.enter.prevent="clearSelectedCover"
                  >
                    ×
                  </span>
                </button>
                <button
                  type="button"
                  class="cover-tile cover-tile-add"
                  :disabled="saving"
                  :title="t('metadata.uploadCover')"
                  @click="pickCoverFile"
                >
                  <span class="cover-add-icon" aria-hidden="true">+</span>
                </button>
              </div>
            </div>
          </div>

          <div class="editor-fields">
            <label>
              <span>{{ t('metadata.fieldTitle') }}</span>
              <input
                v-model="editForm.title"
                type="text"
                @input="onTitleOrArtistInput"
              />
            </label>
            <label>
              <span>{{ t('metadata.fieldFilename') }}</span>
              <input
                v-model="editForm.filename"
                type="text"
                :placeholder="t('metadata.filenameHint')"
                @input="onFilenameInput"
              />
            </label>
            <label>
              <span>{{ t('metadata.fieldArtist') }}</span>
              <div class="artist-chips" :class="{ disabled: saving }">
                <span
                  v-for="(name, index) in editArtists"
                  :key="`${name}-${index}`"
                  class="artist-chip"
                >
                  <span
                    class="artist-chip-text"
                    :title="t('metadata.editArtistChip')"
                    @click="editArtistChip(index)"
                  >{{ name }}</span>
                  <button
                    type="button"
                    class="artist-chip-remove"
                    :disabled="saving"
                    :aria-label="t('metadata.removeArtist', { name })"
                    @click="removeEditArtist(index)"
                  >
                    ×
                  </button>
                </span>
                <input
                  v-model="artistDraft"
                  class="artist-chip-input"
                  type="text"
                  :disabled="saving"
                  :placeholder="editArtists.length ? '' : t('metadata.artistChipPlaceholder')"
                  @keydown="onArtistDraftKeydown"
                  @blur="commitArtistDraft"
                />
                <button
                  v-if="editArtists.length"
                  type="button"
                  class="artist-chips-clear"
                  :disabled="saving"
                  :title="t('metadata.clearArtists')"
                  @click="clearEditArtists"
                >
                  ×
                </button>
              </div>
            </label>
            <label>
              <span>{{ t('metadata.fieldAlbum') }}</span>
              <input v-model="editForm.album" type="text" />
            </label>
            <label>
              <span>{{ t('metadata.fieldAlbumArtist') }}</span>
              <select
                v-model="albumArtistChoice"
                class="album-artist-select"
                :disabled="saving || albumArtistOptions.length === 0"
                @change="onAlbumArtistChange"
              >
                <option
                  v-if="albumArtistOptions.length === 0"
                  value=""
                  disabled
                >
                  {{ t('metadata.albumArtistEmpty') }}
                </option>
                <option
                  v-for="option in albumArtistOptions"
                  :key="option.value"
                  :value="option.value"
                >
                  {{ option.label }}
                </option>
              </select>
            </label>
            <label>
              <span>{{ t('metadata.fieldYear') }}</span>
              <input v-model="editForm.year" type="text" inputmode="numeric" />
            </label>
            <p v-if="editForm.score" class="editor-meta">
              {{ t('metadata.fieldScore') }}: {{ editForm.score }}%
            </p>
          </div>

          <input
            ref="coverInput"
            type="file"
            accept="image/png,image/jpeg,image/webp,image/gif"
            hidden
            @change="onCoverFileSelected"
          />
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

.candidate-card.is-file {
  border-style: dashed;
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

.candidate-score.file-edit {
  background: transparent;
  color: var(--color-accent);
  border: 1px solid var(--color-accent);
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
  width: min(560px, 100%);
  max-height: min(90vh, 780px);
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
  grid-template-columns: 156px 1fr;
  gap: 16px;
  align-items: stretch;
  padding: 20px;
}

.editor-cover-col {
  display: flex;
  flex-direction: column;
  gap: 10px;
  min-width: 0;
  /* Match right column height; overflow scrolls inside cover-grid. */
  height: 0;
  min-height: 100%;
  overflow: hidden;
}

.editor-cover {
  position: relative;
  width: 100%;
  aspect-ratio: 1;
  flex-shrink: 0;
  border-radius: var(--radius-control);
  overflow: hidden;
  background: var(--color-bg);
  border: 1px solid var(--color-border);
}

.editor-cover.empty {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 148px;
}

.editor-cover-hint {
  font-size: 11px;
  text-align: center;
  padding: 8px;
  color: var(--color-text-muted);
  line-height: 1.3;
}

.editor-cover img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.cover-clear {
  position: absolute;
  right: 8px;
  bottom: 8px;
  z-index: 2;
  width: 28px;
  height: 28px;
  border: none;
  border-radius: 999px;
  background: rgba(15, 23, 42, 0.72);
  color: #fff;
  font-size: 18px;
  line-height: 28px;
  text-align: center;
  cursor: pointer;
  box-shadow: 0 1px 3px rgba(15, 23, 42, 0.35);
}

.cover-clear:hover:not(:disabled) {
  background: rgba(185, 28, 28, 0.9);
}

.cover-clear:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.cover-picker {
  flex: 1 1 auto;
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
}

.cover-picker-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
  margin-bottom: 8px;
  font-size: 11px;
  color: var(--color-text-muted);
  flex-shrink: 0;
}

.cover-picker-count {
  font-variant-numeric: tabular-nums;
}

.cover-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  grid-auto-rows: max-content;
  gap: 8px;
  flex: 1 1 auto;
  align-content: start;
  align-items: start;
  overflow-x: hidden;
  overflow-y: auto;
  padding-right: 4px;
  min-height: 0;
  scrollbar-gutter: stable;
}

.cover-grid::-webkit-scrollbar {
  width: 6px;
}

.cover-grid::-webkit-scrollbar-thumb {
  background: color-mix(in srgb, var(--color-text-muted) 45%, transparent);
  border-radius: 999px;
}

.cover-tile {
  position: relative;
  width: 100%;
  /* padding-bottom square avoids aspect-ratio overlap inside scrollable grids */
  height: 0;
  padding-bottom: 100%;
  border: 2px solid transparent;
  border-radius: 8px;
  overflow: hidden;
  background: var(--color-bg);
  box-shadow: 0 1px 3px rgba(15, 23, 42, .08);
  cursor: pointer;
  align-self: start;
}

.cover-tile img {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}

.cover-tile.active {
  border-color: var(--color-accent);
}

.cover-check {
  position: absolute;
  top: 4px;
  right: 4px;
  z-index: 1;
  width: 16px;
  height: 16px;
  border-radius: 999px;
  background: var(--color-accent);
  color: #fff;
  font-size: 10px;
  line-height: 16px;
  text-align: center;
  box-shadow: 0 1px 2px rgba(15, 23, 42, .2);
}

.cover-tile-clear {
  position: absolute;
  right: 4px;
  bottom: 4px;
  z-index: 2;
  width: 18px;
  height: 18px;
  border-radius: 999px;
  background: rgba(15, 23, 42, 0.72);
  color: #fff;
  font-size: 14px;
  line-height: 18px;
  text-align: center;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.25);
}

.cover-tile-clear:hover {
  background: rgba(185, 28, 28, 0.9);
}

.cover-tile-add {
  border-style: dashed;
  box-shadow: none;
  color: var(--color-text-muted);
}

.cover-tile-add:hover:not(:disabled) {
  border-color: var(--color-accent);
  color: var(--color-accent);
}

.cover-add-icon {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 22px;
  line-height: 1;
  font-weight: 300;
}

.cover-tile:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.editor-fields {
  display: flex;
  flex-direction: column;
  gap: 12px;
  min-width: 0;
  /* Keep content-sized height so it drives the grid row. */
  min-height: min-content;
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

.artist-chips {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  min-height: 38px;
  padding: 6px 28px 6px 8px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-control);
  background: var(--color-bg);
  position: relative;
}

.artist-chips.disabled {
  opacity: 0.7;
}

.artist-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  max-width: 100%;
  padding: 2px 4px 2px 8px;
  border-radius: 999px;
  background: color-mix(in srgb, var(--color-accent) 12%, var(--color-bg));
  color: var(--color-text);
  font-size: 12px;
  line-height: 1.4;
}

.artist-chip-text {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  cursor: pointer;
}

.artist-chip-remove {
  flex-shrink: 0;
  width: 16px;
  height: 16px;
  border: none;
  border-radius: 999px;
  background: color-mix(in srgb, var(--color-text-muted) 20%, transparent);
  color: var(--color-text-muted);
  font-size: 12px;
  line-height: 16px;
  padding: 0;
  cursor: pointer;
}

.artist-chip-remove:hover:not(:disabled) {
  background: color-mix(in srgb, var(--color-text) 18%, transparent);
  color: var(--color-text);
}

.artist-chip-input {
  flex: 1 1 72px;
  min-width: 72px;
  border: none !important;
  outline: none;
  background: transparent !important;
  padding: 4px 0 !important;
  font-size: 13px;
  color: var(--color-text);
}

.artist-chips-clear {
  position: absolute;
  right: 6px;
  bottom: 6px;
  width: 18px;
  height: 18px;
  border: none;
  border-radius: 999px;
  background: transparent;
  color: var(--color-text-muted);
  font-size: 14px;
  line-height: 18px;
  padding: 0;
  cursor: pointer;
}

.artist-chips-clear:hover:not(:disabled) {
  color: var(--color-text);
}

.album-artist-select {
  width: 100%;
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

  .editor-cover-col {
    height: auto;
    min-height: 0;
    max-height: 360px;
  }

  .cover-grid {
    grid-template-columns: repeat(4, minmax(0, 1fr));
  }
}
</style>
