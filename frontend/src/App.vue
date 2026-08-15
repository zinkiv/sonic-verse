<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useLibraryStore } from './stores/library'
import { useTheme, type ThemeMode } from './composables/useTheme'

const route = useRoute()
const router = useRouter()
const libraryStore = useLibraryStore()
const { t } = useI18n()
const { mode: themeMode, cycleMode } = useTheme()

const isAuthPage = computed(() => route.name === 'login' || route.name === 'setup')

const currentPage = computed(() => {
  if (route.name === 'metadata') return 'metadata'
  if (route.name === 'settings') return 'settings'
  return 'library'
})

const THEME_LABEL: Record<ThemeMode, string> = {
  system: 'theme.system',
  light: 'theme.light',
  dark: 'theme.dark',
}

const themeTitle = computed(
  () => `${t('theme.label')} · ${t(THEME_LABEL[themeMode.value])}`
)

const searchOpen = ref(false)
const searchQuery = ref('')
const searchInput = ref<HTMLInputElement | null>(null)

async function openSearch() {
  searchOpen.value = true
  await nextTick()
  searchInput.value?.focus()
}

function collapseIfEmpty() {
  if (!searchQuery.value) searchOpen.value = false
}

function clearSearch() {
  searchQuery.value = ''
  searchOpen.value = false
}

// Debounced so a burst of keystrokes results in one request.
let searchTimer: ReturnType<typeof setTimeout> | undefined
watch(searchQuery, (value) => {
  clearTimeout(searchTimer)
  searchTimer = setTimeout(() => libraryStore.setSearch(value.trim()), 300)
})

onBeforeUnmount(() => clearTimeout(searchTimer))

function switchPage(page: string) {
  if (page === 'library') {
    // Already on library: remount won't run, so sync disk → DB here.
    if (route.name === 'library') {
      void libraryStore.syncMusicFromDisk()
      return
    }
    void router.push('/')
    return
  }
  if (page === 'metadata') {
    if (route.name === 'metadata') {
      libraryStore.bumpMetadataResync()
      return
    }
    void router.push('/metadata')
    return
  }
  void router.push(`/${page}`)
}
</script>

<template>
  <div id="app-container">
    <nav v-if="!isAuthPage" class="top-nav">
      <a href="#" class="brand" @click.prevent="switchPage('library')">
        <span class="brand-mark">♪</span>
        <span>{{ t('app.name') }}</span>
      </a>

      <div class="main-tabs">
        <a
          href="#"
          class="main-tab"
          :class="{ active: currentPage === 'library' }"
          @click.prevent="switchPage('library')"
        >
          {{ t('nav.library') }}
        </a>
        <a
          href="#"
          class="main-tab"
          :class="{ active: currentPage === 'metadata' }"
          @click.prevent="switchPage('metadata')"
        >
          {{ t('nav.metadata') }}
        </a>
      </div>

      <div class="nav-actions">
        <div class="tool-actions">
          <button
            v-if="currentPage === 'library' && !searchOpen"
            class="icon-btn"
            :title="t('nav.search')"
            :aria-label="t('nav.search')"
            @click="openSearch"
          >
            <svg width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.75" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" d="M21 21l-5.2-5.2m1.45-4.55a6.75 6.75 0 11-13.5 0 6.75 6.75 0 0113.5 0z"/>
            </svg>
          </button>

          <div v-else-if="currentPage === 'library' && searchOpen" class="search-field">
            <svg width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.75" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" d="M21 21l-5.2-5.2m1.45-4.55a6.75 6.75 0 11-13.5 0 6.75 6.75 0 0113.5 0z"/>
            </svg>
            <input
              ref="searchInput"
              type="text"
              v-model="searchQuery"
              :placeholder="t('nav.searchPlaceholder')"
              @blur="collapseIfEmpty"
              @keydown.esc="clearSearch"
            />
            <button
              v-if="searchQuery"
              class="clear-btn"
              :title="t('nav.closeSearch')"
              :aria-label="t('nav.closeSearch')"
              @mousedown.prevent="clearSearch"
            >
              <svg width="12" height="12" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12"/>
              </svg>
            </button>
          </div>

          <button
            class="icon-btn"
            :title="themeTitle"
            :aria-label="themeTitle"
            @click="cycleMode"
          >
            <svg
              v-if="themeMode === 'system'"
              width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.75" viewBox="0 0 24 24"
            >
              <path stroke-linecap="round" stroke-linejoin="round" d="M8 20h8M9.5 17H5.75A1.75 1.75 0 014 15.25V5.75A1.75 1.75 0 015.75 4h12.5A1.75 1.75 0 0120 5.75v9.5A1.75 1.75 0 0118.25 17H14.5"/>
            </svg>
            <svg
              v-else-if="themeMode === 'light'"
              width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.75" viewBox="0 0 24 24"
            >
              <path stroke-linecap="round" stroke-linejoin="round" d="M12 3.5v1.5m0 14v1.5M20.5 12H19m-14 0H3.5m14.36 5.36l-1.06-1.06M6.7 6.7L5.64 5.64m12.72 0L17.3 6.7M6.7 17.3l-1.06 1.06M16 12a4 4 0 11-8 0 4 4 0 018 0z"/>
            </svg>
            <svg
              v-else
              width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.75" viewBox="0 0 24 24"
            >
              <path stroke-linecap="round" stroke-linejoin="round" d="M20.2 14.3A8.5 8.5 0 019.7 3.8 8.5 8.5 0 1012 21a8.45 8.45 0 008.2-6.7z"/>
            </svg>
          </button>

          <button
            class="icon-btn"
            :class="{ active: currentPage === 'settings' }"
            :title="t('nav.settings')"
            :aria-label="t('nav.settings')"
            @click="switchPage('settings')"
          >
            <svg width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.75" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z"/>
              <path stroke-linecap="round" stroke-linejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"/>
            </svg>
          </button>
        </div>
      </div>
    </nav>

    <!-- Main Content -->
    <router-view />
  </div>
</template>

<style scoped>
.top-nav {
  display: grid;
  grid-template-columns: 1fr auto 1fr;
  align-items: center;
  gap: 16px;
  padding: 14px 24px;
  border-bottom: 1px solid var(--color-border);
  position: sticky;
  top: 0;
  background: var(--color-bg);
  z-index: 10;
}

.brand {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 600;
  font-size: 15px;
  letter-spacing: .02em;
  justify-self: start;
}

.brand-mark {
  color: var(--color-accent);
  font-size: 16px;
}

.main-tabs {
  display: flex;
  gap: 4px;
  justify-self: center;
}

.main-tab {
  padding: 6px 16px;
  border-radius: 999px;
  color: var(--color-text-muted);
  font-size: 14px;
  font-weight: 600;
  transition:
    background-color var(--motion-duration) var(--motion-ease),
    color var(--motion-duration) var(--motion-ease);
}

.main-tab:hover {
  color: var(--color-text);
}

.main-tab.active {
  background: var(--color-accent);
  color: #fff;
}

.nav-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  justify-self: end;
}

.tool-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.icon-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  width: 34px;
  height: 34px;
  padding: 0;
  background: transparent;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-control);
  color: var(--color-text);
  transition:
    transform var(--motion-duration) var(--motion-ease),
    border-color var(--motion-duration) var(--motion-ease),
    color var(--motion-duration) var(--motion-ease);
}

.icon-btn:hover {
  transform: scale(1.06);
  border-color: var(--color-accent);
}

.icon-btn.active {
  color: var(--color-accent);
  border-color: var(--color-accent);
}

.icon-btn svg {
  display: block;
}

.search-field {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 0 12px;
  height: 34px;
  background: transparent;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-control);
  color: var(--color-text-muted);
}

.search-field:focus-within {
  border-color: var(--color-accent);
}

.search-field input {
  background: transparent;
  border: none;
  outline: none;
  color: var(--color-text);
  font-size: 13px;
  width: 220px;
}

.search-field input::placeholder {
  color: var(--color-text-muted);
}

.clear-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  background: transparent;
  border: none;
  color: var(--color-text-muted);
  padding: 0;
}

.clear-btn:hover {
  color: var(--color-text);
}
</style>
