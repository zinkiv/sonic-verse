import { createI18n } from 'vue-i18n'

import en from './locales/en'
import zh from './locales/zh'

export const SUPPORTED_LOCALES = ['zh', 'en'] as const
export type Locale = (typeof SUPPORTED_LOCALES)[number]

const STORAGE_KEY = 'sonicverse-locale'

const HTML_LANG: Record<Locale, string> = {
  zh: 'zh-CN',
  en: 'en',
}

function isLocale(value: string | null): value is Locale {
  return value !== null && SUPPORTED_LOCALES.includes(value as Locale)
}

// Chinese is the project's primary language; English is opt-in rather than
// browser-detected, so an English-locale browser doesn't silently change the UI.
function initialLocale(): Locale {
  const stored = localStorage.getItem(STORAGE_KEY)
  return isLocale(stored) ? stored : 'zh'
}

export const i18n = createI18n({
  legacy: false,
  locale: initialLocale(),
  fallbackLocale: 'en',
  messages: { zh, en },
})

export function setLocale(locale: Locale) {
  i18n.global.locale.value = locale
  localStorage.setItem(STORAGE_KEY, locale)
  document.documentElement.lang = HTML_LANG[locale]
  document.title = i18n.global.t('app.name')
}

export function currentLocale(): Locale {
  return i18n.global.locale.value as Locale
}

// Apply the resolved locale to <html> and the tab title on first load.
setLocale(currentLocale())
