<script setup lang="ts">
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'

defineOptions({ inheritAttrs: false })

defineProps<{
  autocomplete?: string
  placeholder?: string
  disabled?: boolean
}>()

const model = defineModel<string>({ default: '' })
const { t } = useI18n()
const visible = ref(false)
</script>

<template>
  <div class="password-wrap">
    <input
      v-model="model"
      :type="visible ? 'text' : 'password'"
      :autocomplete="autocomplete"
      :placeholder="placeholder"
      :disabled="disabled"
      spellcheck="false"
      v-bind="$attrs"
    />
    <button
      type="button"
      class="toggle"
      :disabled="disabled"
      :aria-label="visible ? t('settings.hidePassword') : t('settings.showPassword')"
      :title="visible ? t('settings.hidePassword') : t('settings.showPassword')"
      @click="visible = !visible"
    >
      <svg v-if="visible" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.75" viewBox="0 0 24 24">
        <path stroke-linecap="round" stroke-linejoin="round" d="M3 3l18 18M10.6 10.6A3 3 0 0012 15a3 3 0 002.4-4.8M9.9 5.1A10.8 10.8 0 0112 5c6 0 10 7 10 7a16.8 16.8 0 01-3.1 3.7M6.1 6.1A16.6 16.6 0 002 12s4 7 10 7a10.4 10.4 0 004.4-.9"/>
      </svg>
      <svg v-else width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.75" viewBox="0 0 24 24">
        <path stroke-linecap="round" stroke-linejoin="round" d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12z"/>
        <circle cx="12" cy="12" r="3"/>
      </svg>
    </button>
  </div>
</template>

<style scoped>
.password-wrap {
  position: relative;
  display: block;
  width: 100%;
}

.password-wrap input {
  width: 100%;
  box-sizing: border-box;
  height: 36px;
  padding: 0 40px 0 12px;
  border: 1.5px solid var(--modal-border, var(--color-border));
  border-radius: var(--radius-control);
  background: var(--modal-input-bg, var(--color-bg));
  color: var(--modal-text, var(--color-text));
  font-size: 14px;
  outline: none;
}

.password-wrap input:focus {
  border-color: var(--color-accent);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--color-accent) 22%, transparent);
}

.toggle {
  position: absolute;
  right: 4px;
  top: 50%;
  transform: translateY(-50%);
  width: 32px;
  height: 32px;
  border: 0;
  border-radius: 8px;
  background: transparent;
  color: var(--modal-mute, var(--color-text-muted));
  display: inline-flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
}

.toggle:hover:not(:disabled) {
  color: var(--modal-text, var(--color-text));
  background: color-mix(in srgb, var(--color-accent) 12%, transparent);
}

.toggle:disabled {
  opacity: 0.35;
  cursor: not-allowed;
}
</style>
