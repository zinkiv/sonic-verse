<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import AccountSettings from '@/components/AccountSettings.vue'
import { api, type AppSettings, type ScanJob } from '@/api'
import { SUPPORTED_LOCALES, setLocale, type Locale } from '@/i18n'
import { useLibraryStore } from '@/stores/library'

const { t, locale } = useI18n()
const libraryStore = useLibraryStore()

const MATCH_PERCENT_MIN = 50
const MATCH_PERCENT_MAX = 100
const MATCH_PERCENT_DEFAULT = 100

function thresholdToPercent(value: number | undefined): number {
  if (value == null || !Number.isFinite(value)) return MATCH_PERCENT_DEFAULT
  // New API: 50–100. Legacy: 0–1 fractions.
  const percent = value <= 1 ? Math.round(value * 100) : Math.round(value)
  return Math.min(MATCH_PERCENT_MAX, Math.max(MATCH_PERCENT_MIN, percent))
}

function clampPercent(value: number): number {
  if (!Number.isFinite(value)) return MATCH_PERCENT_DEFAULT
  return Math.min(MATCH_PERCENT_MAX, Math.max(MATCH_PERCENT_MIN, Math.round(value)))
}

function onThresholdInput(event: Event) {
  const target = event.target as HTMLInputElement
  thresholdPercent.value = clampPercent(Number(target.value))
}

function onThresholdCommit(event: Event) {
  onThresholdInput(event)
  void saveThreshold()
}

const serverSettings = ref<AppSettings | null>(null)
const error = ref<string | null>(null)
const settingsReady = ref(false)
const thresholdPercent = ref(MATCH_PERCENT_DEFAULT)
const savedPercent = ref(MATCH_PERCENT_DEFAULT)
const thresholdBusy = ref(false)
const thresholdMessage = ref<string | null>(null)
const thresholdMessageTone = ref<'ok' | 'error' | null>(null)

const scanJob = ref<ScanJob | null>(null)
const scanBusy = ref(false)
const scanMessage = ref<string | null>(null)
const scanMessageTone = ref<'ok' | 'error' | null>(null)

let pollTimer: ReturnType<typeof setTimeout> | undefined

const LOCALE_LABEL: Record<Locale, string> = {
  zh: 'locale.zh',
  en: 'locale.en',
}

const isScanning = computed(() => {
  const status = scanJob.value?.status
  return status === 'pending' || status === 'running'
})

const scanPercent = computed(() => {
  const job = scanJob.value
  if (!job || job.tracks_found <= 0) return 0
  return Math.min(100, Math.round((job.tracks_processed / job.tracks_found) * 100))
})

function clearPoll() {
  clearTimeout(pollTimer)
  pollTimer = undefined
}

function schedulePoll(jobId: string) {
  clearPoll()
  pollTimer = setTimeout(() => void pollJob(jobId), 1000)
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
      scanMessage.value = t('settings.scanCompleted', { processed: job.tracks_processed })
      scanMessageTone.value = 'ok'
      await libraryStore.reloadLibrary()
    } else if (job.status === 'failed') {
      scanMessage.value = t('settings.scanFailed', {
        error: job.error_msg || t('errors.loadFailed'),
      })
      scanMessageTone.value = 'error'
    } else if (job.status === 'cancelled') {
      scanMessage.value = t('settings.scanCancelled')
      scanMessageTone.value = 'ok'
    }
  } catch (err) {
    scanBusy.value = false
    scanMessage.value = err instanceof Error ? err.message : t('settings.scanStartFailed')
    scanMessageTone.value = 'error'
  }
}

async function startScan() {
  if (!serverSettings.value || isScanning.value || scanBusy.value) return

  scanBusy.value = true
  scanMessage.value = null
  scanMessageTone.value = null

  try {
    const job = await api.post<ScanJob>('/scanner/scan', {
      root_path: serverSettings.value.music_path,
    })
    scanJob.value = job
    schedulePoll(job.id)
  } catch (err) {
    scanBusy.value = false
    scanMessage.value = err instanceof Error ? err.message : t('settings.scanStartFailed')
    scanMessageTone.value = 'error'
  }
}

async function cancelScan() {
  const job = scanJob.value
  if (!job || !isScanning.value) return

  try {
    scanJob.value = await api.post<ScanJob>(`/scanner/jobs/${job.id}/cancel`)
  } catch (err) {
    scanMessage.value = err instanceof Error ? err.message : t('settings.scanStartFailed')
    scanMessageTone.value = 'error'
  }
}

async function saveThreshold() {
  if (!settingsReady.value || thresholdBusy.value) return

  const percent = clampPercent(thresholdPercent.value)
  thresholdPercent.value = percent
  if (percent === savedPercent.value) return

  thresholdBusy.value = true
  thresholdMessage.value = null
  thresholdMessageTone.value = null
  try {
    serverSettings.value = await api.patch<AppSettings>('/settings', {
      match_confidence_threshold: percent,
    })
    const next = thresholdToPercent(serverSettings.value.match_confidence_threshold)
    thresholdPercent.value = next
    savedPercent.value = next
  } catch (err) {
    thresholdPercent.value = savedPercent.value
    thresholdMessage.value =
      err instanceof Error ? err.message : t('settings.matchThresholdSaveFailed')
    thresholdMessageTone.value = 'error'
  } finally {
    thresholdBusy.value = false
  }
}

onMounted(async () => {
  try {
    serverSettings.value = await api.get<AppSettings>('/settings')
    const percent = thresholdToPercent(serverSettings.value.match_confidence_threshold)
    thresholdPercent.value = percent
    savedPercent.value = percent
    settingsReady.value = true
  } catch (err) {
    error.value = err instanceof Error ? err.message : t('settings.loadFailed')
  }
})

onBeforeUnmount(() => clearPoll())
</script>

<template>
  <div class="settings">
    <h1>{{ t('settings.title') }}</h1>

    <AccountSettings />

    <!-- 外观 -->
    <section class="card">
      <h2 class="card-title">{{ t('settings.appearance') }}</h2>
      <div class="rows">
        <div class="row">
          <span class="label">{{ t('locale.label') }}</span>
          <div class="segmented" role="group" :aria-label="t('locale.label')">
            <button
              v-for="option in SUPPORTED_LOCALES"
              :key="option"
              type="button"
              :class="{ active: locale === option }"
              @click="setLocale(option)"
            >
              {{ t(LOCALE_LABEL[option]) }}
            </button>
          </div>
        </div>
      </div>
    </section>

    <!-- 曲库 -->
    <section class="card">
      <div class="card-header">
        <h2 class="card-title">{{ t('settings.librarySection') }}</h2>
        <div class="scan-actions">
          <button
            v-if="isScanning"
            type="button"
            class="link-btn"
            @click="cancelScan"
          >
            {{ t('settings.cancelScan') }}
          </button>
          <button
            type="button"
            class="scan-btn"
            :disabled="!serverSettings || isScanning || scanBusy"
            @click="startScan"
          >
            {{ isScanning || scanBusy ? t('settings.scanning') : t('settings.scan') }}
          </button>
        </div>
      </div>
      <div v-if="serverSettings" class="rows">
        <div class="row">
          <span class="label">{{ t('settings.audioExtensions') }}</span>
          <span class="value mono">{{ serverSettings.audio_extensions.join(' ') }}</span>
        </div>
      </div>

      <div v-if="isScanning && scanJob" class="scan-status">
        <div class="scan-status-row">
          <span>
            {{
              scanJob.status === 'pending'
                ? t('settings.scanQueued')
                : t('settings.scanProgress', {
                    processed: scanJob.tracks_processed,
                    found: scanJob.tracks_found,
                  })
            }}
          </span>
          <span v-if="scanJob.tracks_found > 0">{{ scanPercent }}%</span>
        </div>
        <div class="progress-track">
          <div class="progress-fill" :style="{ width: `${scanPercent}%` }"></div>
        </div>
      </div>

      <p
        v-else-if="scanMessage"
        class="scan-message"
        :class="scanMessageTone"
      >
        {{ scanMessage }}
      </p>

      <p v-if="error" class="error">{{ error }}</p>
    </section>

    <!-- 匹配 -->
    <section class="card">
      <h2 class="card-title">{{ t('settings.matchSection') }}</h2>
      <div v-if="settingsReady" class="rows">
        <div class="row threshold-row">
          <span class="label">{{ t('settings.matchThreshold') }}</span>
          <div class="threshold-control">
            <input
              class="threshold-slider"
              type="range"
              :min="MATCH_PERCENT_MIN"
              :max="MATCH_PERCENT_MAX"
              step="1"
              :value="thresholdPercent"
              :disabled="thresholdBusy"
              :aria-label="t('settings.matchThreshold')"
              @input="onThresholdInput"
              @change="onThresholdCommit"
            />
            <input
              class="threshold-number"
              type="number"
              :min="MATCH_PERCENT_MIN"
              :max="MATCH_PERCENT_MAX"
              step="1"
              :value="thresholdPercent"
              :disabled="thresholdBusy"
              @change="onThresholdCommit"
            />
            <span class="unit">%</span>
          </div>
        </div>
      </div>
      <p class="hint">{{ t('settings.matchThresholdHint') }}</p>
      <p v-if="thresholdMessage" class="scan-message" :class="thresholdMessageTone">
        {{ thresholdMessage }}
      </p>
    </section>

    <!-- 关于 -->
    <section class="card">
      <h2 class="card-title">{{ t('settings.about') }}</h2>
      <div class="rows">
        <div class="row">
          <span class="label">{{ t('app.name') }}</span>
          <span class="value">{{ t('app.tagline') }}</span>
        </div>
        <div class="row">
          <span class="label">{{ t('settings.version') }}</span>
          <span class="value mono">{{ serverSettings?.app_version ?? '—' }}</span>
        </div>
      </div>
    </section>
  </div>
</template>

<style scoped>
.settings {
  padding: 28px 32px 48px;
  max-width: 640px;
  margin: 0 auto;
}

.settings h1 {
  font-size: 22px;
  font-weight: 600;
  margin: 0 0 24px;
}

.card {
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-card);
  padding: 16px 18px 4px;
  margin-bottom: 16px;
}

.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 4px;
}

.card-title {
  margin: 0 0 8px;
  font-size: 15px;
  font-weight: 600;
  color: var(--color-text);
}

.card-header .card-title {
  margin-bottom: 0;
}

.scan-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}

.rows {
  display: flex;
  flex-direction: column;
}

.row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  min-height: 44px;
  padding: 10px 0;
  font-size: 14px;
  border-top: 1px solid var(--color-border);
}

.rows .row:first-child {
  border-top: none;
}

.label {
  flex-shrink: 0;
  color: var(--color-text);
}

.value {
  text-align: right;
  color: var(--color-text-muted);
  font-size: 13px;
  line-height: 1.4;
  word-break: break-all;
}

.mono {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
}

.threshold-row {
  align-items: center;
}

.threshold-control {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
  flex: 1;
  justify-content: flex-end;
}

.threshold-slider {
  flex: 1;
  min-width: 80px;
  max-width: 180px;
  accent-color: var(--color-accent);
  cursor: pointer;
}

.threshold-number {
  width: 56px;
  padding: 4px 6px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-control);
  background: var(--color-bg);
  color: var(--color-text);
  font-size: 13px;
  text-align: right;
}

.threshold-number:disabled {
  opacity: 0.6;
}

.unit {
  color: var(--color-text-muted);
  font-size: 13px;
  flex-shrink: 0;
}

.hint {
  margin: 0 0 12px;
  font-size: 12px;
  color: var(--color-text-muted);
  line-height: 1.5;
}

.segmented {
  display: inline-flex;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-control);
  overflow: hidden;
}

.segmented button {
  background: transparent;
  border: none;
  color: var(--color-text-muted);
  padding: 6px 14px;
  font-size: 13px;
  cursor: pointer;
  transition:
    background-color var(--motion-duration) var(--motion-ease),
    color var(--motion-duration) var(--motion-ease);
}

.segmented button + button {
  border-left: 1px solid var(--color-border);
}

.segmented button.active {
  background: var(--color-accent);
  color: #fff;
}

.link-btn {
  background: none;
  border: 1px solid var(--color-border);
  color: var(--color-text);
  border-radius: var(--radius-control);
  padding: 4px 10px;
  font-size: 12px;
  cursor: pointer;
  flex-shrink: 0;
  transition: background-color var(--motion-duration) var(--motion-ease);
}

.link-btn:hover:not(:disabled) {
  background: var(--color-border);
}

.scan-btn {
  background: var(--color-accent);
  color: #fff;
  border: none;
  border-radius: var(--radius-control);
  padding: 6px 14px;
  font-size: 13px;
  cursor: pointer;
  flex-shrink: 0;
  transition: opacity var(--motion-duration) var(--motion-ease);
}

.scan-btn:hover:not(:disabled) {
  opacity: 0.9;
}

.scan-btn:disabled {
  opacity: 0.5;
  cursor: default;
}

.scan-status {
  margin: 8px 0 12px;
  padding-top: 12px;
  border-top: 1px solid var(--color-border);
}

.scan-status-row {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  font-size: 12px;
  color: var(--color-text-muted);
  margin-bottom: 8px;
}

.progress-track {
  height: 6px;
  border-radius: 999px;
  background: var(--color-bg);
  overflow: hidden;
}

.progress-fill {
  height: 100%;
  background: var(--color-accent);
  border-radius: 999px;
  transition: width 0.2s ease-out;
}

.scan-message {
  margin: 4px 0 12px;
  font-size: 13px;
}

.scan-message.ok {
  color: #22c55e;
}

.scan-message.error {
  color: #ef4444;
}

.error {
  margin: 4px 0 12px;
  font-size: 13px;
  color: #ef4444;
}

@media (max-width: 640px) {
  .settings {
    padding: 20px 16px 40px;
  }

  .card-header {
    flex-wrap: wrap;
  }

  .row {
    flex-wrap: wrap;
    gap: 8px;
  }

  .value {
    text-align: left;
    width: 100%;
  }
}
</style>
