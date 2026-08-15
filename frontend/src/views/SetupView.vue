<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '@/stores/auth'

const { t } = useI18n()
const router = useRouter()
const auth = useAuthStore()

const username = ref('')
const password = ref('')
const confirm = ref('')
const busy = ref(false)
const error = ref('')

async function onSubmit() {
  if (busy.value) return
  const name = username.value.trim()
  if (!name || !password.value) return
  if (password.value !== confirm.value) {
    error.value = t('setup.passwordMismatch')
    return
  }
  busy.value = true
  error.value = ''
  try {
    await auth.completeSetup(name, password.value)
    await router.replace({ name: 'library' })
  } catch (e) {
    error.value = e instanceof Error ? e.message : t('setup.failed')
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="auth-page">
    <div class="auth-card">
      <div class="brand">
        <span class="mark" aria-hidden="true">♪</span>
        <h1>{{ t('app.name') }}</h1>
      </div>
      <p class="desc">{{ t('setup.desc') }}</p>
      <form class="form" @submit.prevent="onSubmit">
        <label class="field">
          <span>{{ t('setup.username') }}</span>
          <input
            v-model="username"
            type="text"
            autocomplete="username"
            maxlength="32"
            :placeholder="t('setup.usernamePlaceholder')"
            :disabled="busy"
          />
        </label>
        <label class="field">
          <span>{{ t('setup.password') }}</span>
          <input
            v-model="password"
            type="password"
            autocomplete="new-password"
            :placeholder="t('setup.passwordPlaceholder')"
            :disabled="busy"
          />
        </label>
        <label class="field">
          <span>{{ t('setup.confirmPassword') }}</span>
          <input
            v-model="confirm"
            type="password"
            autocomplete="new-password"
            :disabled="busy"
          />
        </label>
        <p v-if="error" class="error">{{ error }}</p>
        <button type="submit" class="submit" :disabled="busy || !username.trim() || !password">
          {{ busy ? t('setup.submitting') : t('setup.submit') }}
        </button>
      </form>
    </div>
  </div>
</template>

<style scoped>
.auth-page {
  min-height: 100vh;
  display: grid;
  place-items: center;
  padding: 24px;
  background: var(--color-bg);
}

.auth-card {
  width: min(100%, 400px);
  padding: 28px 26px 24px;
  border-radius: var(--radius-card);
  border: 1px solid var(--color-border);
  background: var(--color-surface);
  box-shadow: 0 12px 32px var(--color-shadow);
}

.brand {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}

.brand h1 {
  margin: 0;
  font-size: 22px;
  font-weight: 650;
}

.mark {
  color: var(--color-accent);
  font-size: 22px;
}

.desc {
  margin: 0 0 20px;
  font-size: 13px;
  line-height: 1.55;
  color: var(--color-text-muted);
}

.form {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.field {
  display: flex;
  flex-direction: column;
  gap: 6px;
  font-size: 13px;
  color: var(--color-text-muted);
}

.field input {
  height: 40px;
  padding: 0 12px;
  border-radius: var(--radius-control);
  border: 1px solid var(--color-border);
  background: var(--color-bg);
  color: var(--color-text);
  font-size: 14px;
  outline: none;
}

.field input:focus {
  border-color: var(--color-accent);
}

.error {
  margin: 0;
  font-size: 13px;
  color: #ef4444;
}

.submit {
  margin-top: 6px;
  height: 40px;
  border: 0;
  border-radius: var(--radius-control);
  background: var(--color-accent);
  color: #fff;
  font-size: 14px;
  font-weight: 600;
}

.submit:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}
</style>
