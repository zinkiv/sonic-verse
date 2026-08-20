<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useLibraryStore, type SubTab } from '@/stores/library'
import { type Album, type Artist, type ArtistImageCandidate, type Track } from '@/api'
import { coverSrc } from '@/utils/cover'
import { formatArtistName, trackArtistLabel } from '@/utils/artists'

const store = useLibraryStore()
const router = useRouter()
const { t } = useI18n()

function providerLabel(name: string | null | undefined): string {
  if (name === 'qqmusic') return t('metadata.providerQq')
  if (name === 'netease') return t('metadata.providerNetease')
  return name || ''
}

const SUB_TABS: SubTab[] = ['albums', 'artists', 'tracks']

const TAB_LABEL: Record<SubTab, string> = {
  albums: 'library.albums',
  artists: 'library.artists',
  tracks: 'library.tracks',
}

const COUNT_LABEL: Record<SubTab, string> = {
  albums: 'library.albumCount',
  artists: 'library.artistCount',
  tracks: 'library.trackCount',
}

const countLabel = computed(() =>
  t(COUNT_LABEL[store.currentSubTab], { count: store.total }, store.total)
)

type ConfirmState = { track: Track } | null

const IMAGE_ACCEPT = 'image/png,image/jpeg,image/webp,image/gif'
const UPLOAD_ID = '__upload__'

const confirm = ref<ConfirmState>(null)
const deleting = ref(false)
const deleteError = ref<string | null>(null)
const matchingArtistId = ref<string | null>(null)
const artistMatchError = ref<string | null>(null)

const pickerArtist = ref<Artist | null>(null)
const pickerCandidates = ref<ArtistImageCandidate[]>([])
const pickerSelectedId = ref<string | null>(null)
const pickerUploadFile = ref<File | null>(null)
const pickerUploadUrl = ref<string | null>(null)
const pickerLoading = ref(false)
const pickerApplying = ref(false)
const pickerError = ref<string | null>(null)
const pickerInput = ref<HTMLInputElement | null>(null)

const confirmTitle = computed(() =>
  confirm.value ? t('library.deleteTrack') : ''
)

const confirmMessage = computed(() =>
  confirm.value
    ? t('library.deleteTrackConfirm', { title: confirm.value.track.title })
    : ''
)

// The first and last page are always shown; the window slides around the
// current page so the control stays a fixed width on large libraries.
const pageNumbers = computed(() => {
  const last = store.totalPages
  if (last <= 1) return []

  const current = store.page
  const pages = new Set([1, last, current])
  if (current - 1 > 1) pages.add(current - 1)
  if (current + 1 < last) pages.add(current + 1)

  return [...pages].sort((a, b) => a - b)
})

// Row numbers continue across pages instead of restarting at 1.
function rowNumber(index: number): number {
  return (store.page - 1) * store.pageSize + index + 1
}

function formatDuration(ms: number | null): string {
  if (!ms) return '--:--'
  const seconds = Math.floor(ms / 1000)
  const mins = Math.floor(seconds / 60)
  const secs = seconds % 60
  return `${mins}:${secs.toString().padStart(2, '0')}`
}

function openDeleteTrack(track: Track) {
  deleteError.value = null
  confirm.value = { track }
}

function closeConfirm() {
  if (deleting.value) return
  confirm.value = null
  deleteError.value = null
}

async function confirmDelete() {
  if (!confirm.value || deleting.value) return
  deleting.value = true
  deleteError.value = null
  try {
    await store.deleteTrack(confirm.value.track.id)
    confirm.value = null
  } catch (err) {
    deleteError.value = err instanceof Error ? err.message : t('library.deleteFailed')
  } finally {
    deleting.value = false
  }
}

function goMatch(track: Track) {
  void router.push({
    name: 'metadata',
    query: { track: track.id, auto: '1' },
  })
}

function openAlbumTracks(album: Album) {
  void store.showAlbumTracks(album)
}

function openArtistTracks(artist: Artist) {
  void store.showArtistTracks(artist)
}

async function matchArtistMeta(artist: Artist, event: Event) {
  event.preventDefault()
  event.stopPropagation()
  if (matchingArtistId.value || pickerApplying.value) return

  matchingArtistId.value = artist.id
  artistMatchError.value = null
  pickerArtist.value = artist
  pickerCandidates.value = []
  pickerSelectedId.value = null
  pickerUploadFile.value = null
  if (pickerUploadUrl.value) URL.revokeObjectURL(pickerUploadUrl.value)
  pickerUploadUrl.value = null
  pickerError.value = null
  pickerLoading.value = true
  try {
    const data = await store.searchArtistMatch(artist.id)
    pickerCandidates.value = data.candidates
    if (data.candidates[0]) {
      pickerSelectedId.value = data.candidates[0].url
    }
  } catch (err) {
    pickerError.value =
      err instanceof Error ? err.message : t('library.matchArtistFailed')
  } finally {
    matchingArtistId.value = null
    pickerLoading.value = false
  }
}

function closeArtistPicker() {
  if (pickerApplying.value) return
  pickerArtist.value = null
  pickerCandidates.value = []
  pickerSelectedId.value = null
  pickerUploadFile.value = null
  if (pickerUploadUrl.value) {
    URL.revokeObjectURL(pickerUploadUrl.value)
    pickerUploadUrl.value = null
  }
  pickerError.value = null
  pickerLoading.value = false
}

function dropBrokenCandidate(url: string) {
  pickerCandidates.value = pickerCandidates.value.filter((item) => item.url !== url)
  if (pickerSelectedId.value !== url) return
  pickerSelectedId.value =
    pickerCandidates.value[0]?.url
    ?? (pickerUploadUrl.value ? UPLOAD_ID : null)
}

function pickArtistImage() {
  pickerInput.value?.click()
}

function onArtistImagePicked(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file || !file.type.startsWith('image/')) return
  pickerUploadFile.value = file
  if (pickerUploadUrl.value) URL.revokeObjectURL(pickerUploadUrl.value)
  pickerUploadUrl.value = URL.createObjectURL(file)
  pickerSelectedId.value = UPLOAD_ID
  pickerError.value = null
}

async function applyArtistPicker() {
  const artist = pickerArtist.value
  if (!artist || pickerApplying.value) return
  if (pickerSelectedId.value === UPLOAD_ID && pickerUploadFile.value) {
    pickerApplying.value = true
    pickerError.value = null
    try {
      await store.applyArtistAvatar(artist.id, { file: pickerUploadFile.value })
      closeArtistPickerAfterSave()
    } catch (err) {
      pickerError.value =
        err instanceof Error ? err.message : t('library.matchArtistFailed')
    } finally {
      pickerApplying.value = false
    }
    return
  }
  if (pickerSelectedId.value && pickerSelectedId.value !== UPLOAD_ID) {
    pickerApplying.value = true
    pickerError.value = null
    try {
      await store.applyArtistAvatar(artist.id, { imageUrl: pickerSelectedId.value })
      closeArtistPickerAfterSave()
    } catch (err) {
      pickerError.value =
        err instanceof Error ? err.message : t('library.matchArtistFailed')
    } finally {
      pickerApplying.value = false
    }
    return
  }
  pickerError.value = t('library.artistMatchNoSelection')
}

function closeArtistPickerAfterSave() {
  pickerApplying.value = false
  closeArtistPicker()
}

const filterBanner = computed(() => {
  if (!store.hasTrackFilter || !store.filterLabel) return null
  if (store.filterAlbumId) {
    return t('library.filterByAlbum', { title: store.filterLabel })
  }
  return t('library.filterByArtist', { name: store.filterLabel })
})

const pageInfo = computed(() => {
  // Numbered pages are only used on the tracks list.
  if (store.currentSubTab !== 'tracks' || store.totalPages < 1 || store.total === 0) {
    return null
  }
  return t('library.pageInfo', {
    page: store.page,
    totalPages: Math.max(store.totalPages, 1),
  })
})

const loadMoreSentinel = ref<HTMLElement | null>(null)
let loadMoreObserver: IntersectionObserver | null = null

function bindLoadMoreObserver(el: HTMLElement | null) {
  loadMoreObserver?.disconnect()
  loadMoreObserver = null
  if (!el) return
  loadMoreObserver = new IntersectionObserver(
    (entries) => {
      if (entries.some((entry) => entry.isIntersecting)) {
        void store.loadMore()
      }
    },
    { rootMargin: '320px 0px' }
  )
  loadMoreObserver.observe(el)
}

watch(loadMoreSentinel, (el) => bindLoadMoreObserver(el))

onMounted(async () => {
  await store.reloadLibrary()
  void store.syncMusicFromDisk()
})

onBeforeUnmount(() => {
  loadMoreObserver?.disconnect()
  loadMoreObserver = null
  if (pickerUploadUrl.value) URL.revokeObjectURL(pickerUploadUrl.value)
})
</script>

<template>
  <div class="main-wrapper">
    <!-- Sub tabs -->
    <div class="sub-tabs">
      <button
        v-for="tab in SUB_TABS"
        :key="tab"
        class="sub-tab"
        :class="{ active: store.currentSubTab === tab }"
        @click="store.setSubTab(tab)"
      >
        {{ t(TAB_LABEL[tab]) }}
      </button>
    </div>

    <!-- Toolbar -->
    <div class="toolbar">
      <div class="toolbar-left">
        <span class="count">{{ countLabel }}</span>
        <span v-if="pageInfo" class="count">{{ pageInfo }}</span>
        <span v-if="store.loading" class="count">{{ t('library.loading') }}</span>
        <span v-else-if="store.syncing" class="count">{{ t('library.syncing') }}</span>
      </div>
      <div v-if="filterBanner" class="filter-banner">
        <span>{{ filterBanner }}</span>
        <button type="button" class="filter-clear" @click="store.clearTrackFilter()">
          {{ t('library.clearFilter') }}
        </button>
      </div>
    </div>

    <!-- Error banner -->
    <div v-if="store.error" class="error-banner">
      <span>{{ store.error }}</span>
      <button @click="store.fetchList()">{{ t('library.retry') }}</button>
    </div>

    <!-- Albums Grid -->
    <div v-if="store.currentSubTab === 'albums'" class="grid">
      <div
        v-for="(album, index) in store.albums"
        :key="album.id"
        class="album-card"
        role="button"
        tabindex="0"
        @click="openAlbumTracks(album)"
        @keydown.enter.prevent="openAlbumTracks(album)"
        @keydown.space.prevent="openAlbumTracks(album)"
      >
        <div class="album-cover">
          <img
            v-if="album.cover_path"
            :src="coverSrc(album.cover_path, album.updated_at)"
            :alt="album.title"
            :loading="index < 12 ? 'eager' : 'lazy'"
            decoding="async"
          />
          <div v-else class="cover-placeholder">♪</div>
        </div>
        <div class="album-meta">
          <p class="album-title">{{ album.title }}</p>
          <p class="album-artist">
            {{ formatArtistName(album.artist?.name) || '—' }}<template v-if="album.year"> · {{ album.year }}</template>
          </p>
        </div>
      </div>

      <!-- Empty state -->
      <div v-if="store.albums.length === 0 && !store.loading" class="empty-state">
        <p>{{ store.search ? t('library.noMatchingAlbums') : t('library.emptyAlbums') }}</p>
        <p v-if="!store.search" class="hint">{{ t('library.emptyHint') }}</p>
      </div>
    </div>

    <!-- Artists Grid -->
    <div v-if="store.currentSubTab === 'artists'" class="artist-grid">
      <p v-if="artistMatchError" class="artist-match-error">{{ artistMatchError }}</p>
      <button
        v-for="(artist, index) in store.artists"
        :key="artist.id"
        type="button"
        class="artist-card"
        @click="openArtistTracks(artist)"
      >
        <div class="artist-avatar-wrap">
          <div class="artist-avatar">
            <img
              v-if="artist.avatar_path"
              :src="coverSrc(artist.avatar_path, artist.updated_at)"
              :alt="artist.name"
              :loading="index < 12 ? 'eager' : 'lazy'"
              decoding="async"
            />
            <div v-else class="avatar-placeholder">{{ artist.name?.charAt(0) }}</div>
          </div>
          <button
            type="button"
            class="artist-match"
            :class="{ busy: matchingArtistId === artist.id }"
            :disabled="matchingArtistId === artist.id"
            :title="t('library.matchArtist')"
            :aria-label="t('library.matchArtist')"
            @click="matchArtistMeta(artist, $event)"
          >
            {{
              matchingArtistId === artist.id
                ? t('library.matchingArtist')
                : t('library.match')
            }}
          </button>
        </div>
        <p class="artist-name">{{ artist.name }}</p>
        <p v-if="artist.avatar_path" class="artist-matched">{{ t('library.matched') }}</p>
      </button>

      <div v-if="store.artists.length === 0 && !store.loading" class="empty-state">
        <p>{{ store.search ? t('library.noMatchingArtists') : t('library.emptyArtists') }}</p>
      </div>
    </div>

    <!-- Tracks List -->
    <div v-if="store.currentSubTab === 'tracks'" class="track-list">
      <div class="track-header">
        <span>#</span>
        <span>{{ t('library.columnTitle') }}</span>
        <span>{{ t('library.columnAlbum') }}</span>
        <span style="text-align: right">{{ t('library.columnDuration') }}</span>
        <span style="text-align: right">{{ t('library.columnActions') }}</span>
      </div>
      <div
        v-for="(track, index) in store.tracks"
        :key="track.id"
        class="track-row"
      >
        <span class="track-num">{{ rowNumber(index) }}</span>
        <div class="track-info">
          <div class="track-thumb">
            <img
              v-if="track.album?.cover_path"
              :src="coverSrc(track.album?.cover_path, track.updated_at)"
              :alt="track.title"
              :loading="index < 8 ? 'eager' : 'lazy'"
              decoding="async"
            />
            <div v-else class="thumb-placeholder">♪</div>
          </div>
          <div>
            <p class="track-name">{{ track.title }}</p>
            <p class="track-artist">{{ trackArtistLabel(track) }}</p>
          </div>
        </div>
        <span class="track-album">{{ track.album?.title }}</span>
        <span class="track-duration">{{ formatDuration(track.duration_ms) }}</span>
        <div class="track-actions">
          <button
            type="button"
            class="row-btn"
            @click="goMatch(track)"
          >
            {{ t('library.match') }}
          </button>
          <button
            type="button"
            class="row-btn danger"
            @click="openDeleteTrack(track)"
          >
            {{ t('library.delete') }}
          </button>
        </div>
      </div>

      <div v-if="store.tracks.length === 0 && !store.loading" class="empty-state">
        <p>{{ store.search ? t('library.noMatchingTracks') : t('library.emptyTracks') }}</p>
      </div>
    </div>

    <!-- Albums / artists: continue the grid instead of leaving a half-empty last row -->
    <div
      v-if="store.hasMore"
      ref="loadMoreSentinel"
      class="load-more-sentinel"
      aria-hidden="true"
    />
    <p v-if="store.loadingMore" class="load-more-status">{{ t('library.loadingMore') }}</p>

    <!-- Tracks keep numbered pagination -->
    <div
      v-if="!store.loading && store.currentSubTab === 'tracks' && store.totalPages > 1"
      class="pagination"
    >
      <button
        class="page-btn"
        :disabled="store.page <= 1 || store.loading"
        @click="store.goToPage(store.page - 1)"
      >
        {{ t('library.previousPage') }}
      </button>

      <template v-for="(num, index) in pageNumbers" :key="num">
        <span v-if="index > 0 && num - pageNumbers[index - 1]! > 1" class="page-gap">…</span>
        <button
          class="page-btn"
          :class="{ active: num === store.page }"
          :disabled="store.loading"
          @click="store.goToPage(num)"
        >
          {{ num }}
        </button>
      </template>

      <button
        class="page-btn"
        :disabled="store.page >= store.totalPages || store.loading"
        @click="store.goToPage(store.page + 1)"
      >
        {{ t('library.nextPage') }}
      </button>
    </div>

    <div
      v-if="confirm"
      class="confirm-backdrop"
      @click.self="closeConfirm"
    >
      <div class="confirm-modal" role="dialog" aria-modal="true">
        <div class="confirm-header">
          <h3>{{ confirmTitle }}</h3>
          <button
            type="button"
            class="confirm-close"
            :disabled="deleting"
            @click="closeConfirm"
          >
            ×
          </button>
        </div>
        <div class="confirm-body">
          <p>{{ confirmMessage }}</p>
          <p v-if="deleteError" class="confirm-error">{{ deleteError }}</p>
        </div>
        <div class="confirm-footer">
          <button
            type="button"
            class="ghost-btn"
            :disabled="deleting"
            @click="closeConfirm"
          >
            {{ t('library.cancel') }}
          </button>
          <button
            type="button"
            class="danger-btn"
            :disabled="deleting"
            @click="confirmDelete"
          >
            {{ deleting ? t('library.confirming') : t('library.delete') }}
          </button>
        </div>
      </div>
    </div>

    <div
      v-if="pickerArtist"
      class="confirm-backdrop"
      @click.self="closeArtistPicker"
    >
      <div class="picker-modal" role="dialog" aria-modal="true">
        <div class="confirm-header">
          <h3>{{ t('library.artistMatchTitle') }} · {{ pickerArtist.name }}</h3>
          <button
            type="button"
            class="confirm-close"
            :disabled="pickerApplying"
            @click="closeArtistPicker"
          >
            ×
          </button>
        </div>
        <div class="picker-body">
          <p v-if="pickerLoading" class="picker-status">{{ t('library.matchingArtist') }}</p>
          <p
            v-else-if="!pickerCandidates.length && !pickerUploadUrl"
            class="picker-status"
          >
            {{ t('library.artistMatchEmpty') }}
          </p>
          <div class="picker-grid">
            <button
              v-for="candidate in pickerCandidates"
              :key="candidate.url"
              type="button"
              class="picker-tile"
              :class="{ active: pickerSelectedId === candidate.url }"
              :disabled="pickerApplying || pickerLoading"
              :title="`${candidate.name} · ${providerLabel(candidate.provider)}`"
              @click="pickerSelectedId = candidate.url"
            >
              <img
                :src="candidate.url"
                alt=""
                referrerpolicy="no-referrer"
                @error="dropBrokenCandidate(candidate.url)"
              />
              <span class="picker-tile-name">
                {{ candidate.name }}
                <em class="picker-tile-provider">{{ providerLabel(candidate.provider) }}</em>
              </span>
            </button>
            <button
              v-if="pickerUploadUrl"
              type="button"
              class="picker-tile"
              :class="{ active: pickerSelectedId === UPLOAD_ID }"
              :disabled="pickerApplying"
              :title="t('library.artistMatchUpload')"
              @click="pickerSelectedId = UPLOAD_ID"
            >
              <img :src="pickerUploadUrl" alt="" />
            </button>
            <button
              type="button"
              class="picker-tile picker-tile-add"
              :disabled="pickerApplying"
              :title="t('library.artistMatchUpload')"
              @click="pickArtistImage"
            >
              <span class="picker-add-icon" aria-hidden="true">+</span>
            </button>
          </div>
          <p v-if="pickerError" class="confirm-error">{{ pickerError }}</p>
        </div>
        <div class="confirm-footer">
          <button
            type="button"
            class="ghost-btn"
            :disabled="pickerApplying"
            @click="closeArtistPicker"
          >
            {{ t('library.cancel') }}
          </button>
          <button
            type="button"
            class="primary-btn"
            :disabled="pickerApplying"
            @click="applyArtistPicker"
          >
            {{ pickerApplying ? t('library.artistMatchApplying') : t('library.artistMatchApply') }}
          </button>
        </div>
      </div>
    </div>
    <input
      ref="pickerInput"
      type="file"
      class="hidden-file"
      :accept="IMAGE_ACCEPT"
      @change="onArtistImagePicked"
    />
  </div>
</template>

<style scoped>
.main-wrapper {
  padding: 24px 32px;
  max-width: 1400px;
  margin: 0 auto;
}

.sub-tabs {
  display: flex;
  gap: 4px;
  margin-bottom: 18px;
}

.sub-tab {
  padding: 6px 16px;
  border: 1px solid transparent;
  border-radius: 999px;
  background: transparent;
  color: var(--color-text-muted);
  font-size: 13px;
  font-weight: 500;
  transition: all var(--motion-duration) var(--motion-ease);
}

.sub-tab:hover:not(.active) {
  color: var(--color-text);
  background: var(--color-surface);
}

.sub-tab.active {
  background: var(--color-surface);
  border-color: var(--color-border);
  color: var(--color-text);
}

.toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 20px;
  flex-wrap: wrap;
}

.toolbar-left {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.filter-banner {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 4px 6px 4px 10px;
  border: 1px solid var(--color-border);
  border-radius: 999px;
  background: var(--color-surface);
  color: var(--color-text);
  font-size: 12px;
}

.filter-clear {
  border: none;
  border-radius: 999px;
  background: transparent;
  color: var(--color-text-muted);
  font-size: 12px;
  padding: 2px 8px;
}

.filter-clear:hover {
  color: var(--color-text);
  background: var(--color-bg);
}

.count {
  color: var(--color-text-muted);
  font-size: 13px;
}

.error-banner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 14px;
  margin-bottom: 16px;
  border: 1px solid #ef4444;
  border-radius: var(--radius-control);
  background: rgba(239, 68, 68, .1);
  color: var(--color-text);
  font-size: 13px;
}

.error-banner button {
  background: transparent;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-control);
  color: var(--color-text);
  padding: 4px 12px;
  font-size: 12px;
  flex-shrink: 0;
}

.load-more-sentinel {
  height: 1px;
  margin-top: 8px;
}

.load-more-status {
  margin-top: 16px;
  text-align: center;
  color: var(--color-text-muted);
  font-size: 13px;
}

.pagination {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  margin-top: 28px;
}

.page-btn {
  min-width: 34px;
  padding: 6px 10px;
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-control);
  color: var(--color-text-muted);
  font-size: 13px;
  transition: all var(--motion-duration) var(--motion-ease);
}

.page-btn:hover:not(:disabled) {
  color: var(--color-text);
  border-color: var(--color-accent);
}

.page-btn.active {
  background: var(--color-accent);
  border-color: var(--color-accent);
  color: #fff;
}

.page-btn:disabled {
  opacity: .45;
  cursor: not-allowed;
}

.page-gap {
  color: var(--color-text-muted);
  font-size: 13px;
  padding: 0 2px;
}

.grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
  gap: 20px 16px;
}

.album-card {
  display: block;
  cursor: pointer;
}

.album-cover {
  position: relative;
  aspect-ratio: 1;
  border-radius: var(--radius-card);
  overflow: hidden;
  box-shadow: 0 4px 12px var(--color-shadow);
  background: var(--color-surface);
  transition: all var(--motion-duration) var(--motion-ease);
  display: flex;
  align-items: center;
  justify-content: center;
}

.album-card:hover .album-cover {
  box-shadow: 0 12px 28px var(--color-shadow);
  transform: translateY(-2px);
}

.album-cover img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.cover-placeholder {
  font-size: 32px;
  color: var(--color-text-muted);
}

.album-meta {
  margin-top: 8px;
}

.album-title {
  font-size: 13px;
  font-weight: 500;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.album-artist {
  font-size: 12px;
  color: var(--color-text-muted);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.artist-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(120px, 1fr));
  gap: 20px 16px;
}

.artist-card {
  display: block;
  width: 100%;
  padding: 0;
  border: none;
  background: transparent;
  color: inherit;
  text-align: center;
  cursor: pointer;
}

.artist-avatar-wrap {
  position: relative;
  width: 100px;
  margin: 0 auto 10px;
}

.artist-avatar {
  width: 100px;
  height: 100px;
  border-radius: 50%;
  overflow: hidden;
  background: var(--color-surface);
  box-shadow: 0 4px 12px var(--color-shadow);
  display: flex;
  align-items: center;
  justify-content: center;
}

.artist-avatar img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.artist-match {
  position: absolute;
  right: -4px;
  bottom: -2px;
  z-index: 1;
  padding: 3px 8px;
  border: none;
  border-radius: 999px;
  background: rgba(15, 23, 42, .72);
  color: #fff;
  font-size: 11px;
  line-height: 1.2;
  opacity: 0;
  transform: translateY(4px);
  transition: all var(--motion-duration) var(--motion-ease);
}

.artist-card:hover .artist-match,
.artist-match:focus-visible,
.artist-match.busy {
  opacity: 1;
  transform: translateY(0);
}

.artist-match:hover:not(:disabled) {
  background: var(--color-accent);
}

.artist-match:disabled {
  cursor: wait;
}

@media (hover: none) {
  .artist-match {
    opacity: 1;
    transform: none;
  }
}

.avatar-placeholder {
  font-size: 32px;
  font-weight: 600;
  color: var(--color-accent);
}

.artist-name {
  font-size: 13px;
  font-weight: 500;
}

.artist-matched {
  margin-top: 2px;
  font-size: 11px;
  color: var(--color-text-muted);
}

.artist-match-error {
  grid-column: 1 / -1;
  margin: 0 0 4px;
  font-size: 12px;
  color: #dc2626;
}

.track-list {
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-card);
  overflow: hidden;
}

.row-btn:disabled {
  opacity: .55;
  cursor: wait;
}

.track-header {
  display: grid;
  grid-template-columns: 50px 1fr 120px 80px 132px;
  gap: 12px;
  padding: 12px 16px;
  border-bottom: 1px solid var(--color-border);
  font-size: 12px;
  color: var(--color-text-muted);
  text-transform: uppercase;
  letter-spacing: .04em;
}

.track-row {
  display: grid;
  grid-template-columns: 50px 1fr 120px 80px 132px;
  gap: 12px;
  padding: 10px 16px;
  border-bottom: 1px solid var(--color-border);
  align-items: center;
  transition: background-color var(--motion-duration) var(--motion-ease);
}

.track-row:last-child {
  border-bottom: none;
}

.track-row:hover {
  background: var(--color-bg);
}

.track-num {
  color: var(--color-text-muted);
  font-size: 13px;
  text-align: center;
}

.track-info {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}

.track-thumb {
  width: 36px;
  height: 36px;
  border-radius: 6px;
  overflow: hidden;
  background: var(--color-bg);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.track-thumb img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.thumb-placeholder {
  font-size: 14px;
  color: var(--color-text-muted);
}

.track-name {
  font-size: 13px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.track-artist {
  font-size: 12px;
  color: var(--color-text-muted);
}

.track-album {
  font-size: 12px;
  color: var(--color-text-muted);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.track-duration {
  font-size: 12px;
  color: var(--color-text-muted);
  text-align: right;
}

.track-actions {
  display: flex;
  justify-content: flex-end;
  gap: 6px;
}

.row-btn {
  padding: 4px 8px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-control);
  background: transparent;
  color: var(--color-text-muted);
  font-size: 12px;
  transition: all var(--motion-duration) var(--motion-ease);
}

.row-btn:hover {
  color: var(--color-text);
  border-color: var(--color-accent);
}

.row-btn.danger:hover {
  color: #dc2626;
  border-color: #dc2626;
}

.empty-state {
  grid-column: 1 / -1;
  text-align: center;
  padding: 60px 20px;
  color: var(--color-text-muted);
}

.empty-state .hint {
  font-size: 12px;
  margin-top: 8px;
}

.confirm-backdrop {
  position: fixed;
  inset: 0;
  z-index: 40;
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

.ghost-btn {
  padding: 6px 14px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-control);
  background: transparent;
  color: var(--color-text-muted);
  font-size: 13px;
}

.ghost-btn:disabled,
.danger-btn:disabled {
  opacity: .5;
  cursor: not-allowed;
}

.danger-btn {
  padding: 6px 14px;
  border: 1px solid #dc2626;
  border-radius: var(--radius-control);
  background: #dc2626;
  color: #fff;
  font-size: 13px;
}

.primary-btn {
  padding: 6px 14px;
  border: 1px solid var(--color-accent);
  border-radius: var(--radius-control);
  background: var(--color-accent);
  color: #fff;
  font-size: 13px;
}

.primary-btn:disabled {
  opacity: .5;
  cursor: not-allowed;
}

.hidden-file {
  display: none;
}

.picker-modal {
  width: min(640px, 100%);
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-card);
  box-shadow: 0 18px 48px rgba(15, 23, 42, .18);
}

.picker-body {
  padding: 16px 20px;
}

.picker-status {
  margin: 0 0 12px;
  font-size: 13px;
  color: var(--color-text-muted);
}

.picker-grid {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 10px;
}

.picker-tile {
  position: relative;
  width: 100%;
  height: 0;
  padding-bottom: 100%;
  border: 2px solid transparent;
  border-radius: 8px;
  overflow: hidden;
  background: var(--color-bg);
  cursor: pointer;
  box-shadow: 0 1px 3px rgba(15, 23, 42, .08);
}

.picker-tile img {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}

.picker-tile.active {
  border-color: var(--color-accent);
}

.picker-tile-name {
  position: absolute;
  left: 0;
  right: 0;
  bottom: 0;
  padding: 4px 6px;
  font-size: 11px;
  line-height: 1.2;
  color: #fff;
  background: linear-gradient(transparent, rgba(15, 23, 42, .72));
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.picker-tile-provider {
  display: block;
  font-style: normal;
  font-size: 10px;
  opacity: 0.82;
}

.picker-tile-add {
  border-style: dashed;
  border-color: var(--color-border);
  box-shadow: none;
  color: var(--color-text-muted);
}

.picker-tile-add:hover:not(:disabled) {
  border-color: var(--color-accent);
  color: var(--color-accent);
}

.picker-add-icon {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 28px;
  font-weight: 300;
  line-height: 1;
}

.picker-tile:disabled {
  cursor: not-allowed;
}

@media (max-width: 720px) {
  .picker-grid {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }

  .track-header,
  .track-row {
    grid-template-columns: 36px 1fr 110px;
  }

  .track-header span:nth-child(3),
  .track-header span:nth-child(4),
  .track-album,
  .track-duration {
    display: none;
  }

  .track-actions {
    grid-column: 3;
  }
}
</style>
