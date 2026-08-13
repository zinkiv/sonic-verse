import { computed, ref, watchEffect } from 'vue'

export const THEME_MODES = ['system', 'light', 'dark'] as const
export type ThemeMode = (typeof THEME_MODES)[number]
export type ResolvedTheme = 'light' | 'dark'

const STORAGE_KEY = 'sonicverse-theme'

const darkQuery = window.matchMedia('(prefers-color-scheme: dark)')

function isThemeMode(value: string | null): value is ThemeMode {
  return value !== null && THEME_MODES.includes(value as ThemeMode)
}

function storedMode(): ThemeMode {
  const stored = localStorage.getItem(STORAGE_KEY)
  return isThemeMode(stored) ? stored : 'system'
}

// Module scope so the nav toggle and the settings page read the same state.
const mode = ref<ThemeMode>(storedMode())
const systemPrefersDark = ref(darkQuery.matches)

darkQuery.addEventListener('change', (event) => {
  systemPrefersDark.value = event.matches
})

const resolved = computed<ResolvedTheme>(() => {
  if (mode.value === 'system') return systemPrefersDark.value ? 'dark' : 'light'
  return mode.value
})

watchEffect(() => {
  document.documentElement.setAttribute('data-theme', resolved.value)
})

export function useTheme() {
  function setMode(next: ThemeMode) {
    mode.value = next
    localStorage.setItem(STORAGE_KEY, next)
  }

  function cycleMode() {
    const index = THEME_MODES.indexOf(mode.value)
    setMode(THEME_MODES[(index + 1) % THEME_MODES.length])
  }

  return { mode, resolved, setMode, cycleMode }
}
