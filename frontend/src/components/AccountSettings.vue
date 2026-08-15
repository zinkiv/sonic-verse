<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import {
  adminSetPassword,
  changePassword,
  createUser,
  deleteUser,
  fetchUsers,
  patchUser,
  type UserPublic,
} from '@/api/auth'
import { useAuthStore } from '@/stores/auth'
import PasswordInput from '@/components/PasswordInput.vue'

const emit = defineEmits<{
  saved: []
}>()

const { t } = useI18n()
const router = useRouter()
const auth = useAuthStore()

const loading = ref(true)
const busy = ref(false)
const error = ref('')
const statusMsg = ref('')
const users = ref<UserPublic[]>([])

const resetOpen = ref(false)
const resetError = ref('')
const oldPassword = ref('')
const newPassword = ref('')
const newConfirm = ref('')

const createOpen = ref(false)
const createError = ref('')
const createUsername = ref('')
const createPassword = ref('')
const createConfirm = ref('')
const createRole = ref<'admin' | 'user'>('user')

const LIST_PAGE_SIZE = 5
const listPage = ref(1)
const listPageCount = computed(() => Math.max(1, Math.ceil(users.value.length / LIST_PAGE_SIZE)))
const pagedUsers = computed(() => {
  const start = (listPage.value - 1) * LIST_PAGE_SIZE
  return users.value.slice(start, start + LIST_PAGE_SIZE)
})

function clampListPage() {
  if (listPage.value > listPageCount.value) listPage.value = listPageCount.value
  if (listPage.value < 1) listPage.value = 1
}

const isAdmin = computed(() => auth.isAdmin)
const anyModalOpen = computed(() => resetOpen.value || createOpen.value)

async function refresh() {
  loading.value = true
  error.value = ''
  try {
    await auth.load()
    if (auth.isAdmin) {
      const data = await fetchUsers()
      users.value = data.users
      clampListPage()
    } else {
      users.value = []
      listPage.value = 1
    }
  } catch (e) {
    error.value = e instanceof Error ? e.message : t('settings.accountLoadFailed')
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  void refresh()
})

function flash(msg: string) {
  statusMsg.value = msg
  emit('saved')
  window.setTimeout(() => {
    if (statusMsg.value === msg) statusMsg.value = ''
  }, 1600)
}

function onLogout() {
  auth.logout()
  void router.replace({ name: 'login' })
}

function openReset() {
  oldPassword.value = ''
  newPassword.value = ''
  newConfirm.value = ''
  resetError.value = ''
  createOpen.value = false
  resetOpen.value = true
}

function closeReset() {
  if (busy.value) return
  resetOpen.value = false
  resetError.value = ''
}

async function onResetPassword() {
  if (busy.value) return
  if (!oldPassword.value || !newPassword.value) return
  if (newPassword.value !== newConfirm.value) {
    resetError.value = t('settings.accountPasswordMismatch')
    return
  }
  busy.value = true
  resetError.value = ''
  error.value = ''
  try {
    await changePassword(oldPassword.value, newPassword.value)
    resetOpen.value = false
    oldPassword.value = ''
    newPassword.value = ''
    newConfirm.value = ''
    flash(t('settings.accountPasswordChanged'))
  } catch (e) {
    resetError.value = e instanceof Error ? e.message : t('settings.accountSaveFailed')
  } finally {
    busy.value = false
  }
}

async function openCreate() {
  createUsername.value = ''
  createPassword.value = ''
  createConfirm.value = ''
  createRole.value = 'user'
  createError.value = ''
  listPage.value = 1
  resetOpen.value = false
  createOpen.value = true
  if (auth.isAdmin) {
    try {
      const data = await fetchUsers()
      users.value = data.users
      clampListPage()
    } catch {
      /* keep existing list */
    }
  }
}

function closeCreate() {
  if (busy.value) return
  createOpen.value = false
  createError.value = ''
}

async function onCreate() {
  if (busy.value || !isAdmin.value) return
  const username = createUsername.value.trim()
  if (!username || !createPassword.value) return
  if (createPassword.value !== createConfirm.value) {
    createError.value = t('settings.accountPasswordMismatch')
    return
  }
  busy.value = true
  createError.value = ''
  error.value = ''
  try {
    await createUser(username, createPassword.value, createRole.value)
    createOpen.value = false
    createUsername.value = ''
    createPassword.value = ''
    createConfirm.value = ''
    createRole.value = 'user'
    flash(t('settings.accountCreated'))
    await refresh()
  } catch (e) {
    createError.value = e instanceof Error ? e.message : t('settings.accountSaveFailed')
  } finally {
    busy.value = false
  }
}

async function onDelete(user: UserPublic) {
  if (busy.value || !isAdmin.value) return
  if (!window.confirm(t('settings.accountDeleteConfirm', { name: user.username }))) return
  busy.value = true
  error.value = ''
  try {
    await deleteUser(user.id)
    if (auth.user?.id === user.id) {
      onLogout()
      return
    }
    flash(t('settings.accountDeleted'))
    await refresh()
  } catch (e) {
    error.value = e instanceof Error ? e.message : t('settings.accountSaveFailed')
  } finally {
    busy.value = false
  }
}

async function onToggleDisabled(user: UserPublic) {
  if (busy.value || !isAdmin.value) return
  busy.value = true
  error.value = ''
  try {
    await patchUser(user.id, { disabled: !user.disabled })
    if (!user.disabled && auth.user?.id === user.id) {
      onLogout()
      return
    }
    flash(user.disabled ? t('settings.accountEnabled') : t('settings.accountDisabled'))
    await refresh()
  } catch (e) {
    error.value = e instanceof Error ? e.message : t('settings.accountSaveFailed')
  } finally {
    busy.value = false
  }
}

async function onAdminReset(user: UserPublic) {
  if (busy.value || !isAdmin.value) return
  const pwd = window.prompt(t('settings.accountAdminResetPrompt', { name: user.username }))
  if (!pwd) return
  busy.value = true
  error.value = ''
  try {
    await adminSetPassword(user.id, pwd)
    flash(t('settings.accountPasswordChanged'))
  } catch (e) {
    error.value = e instanceof Error ? e.message : t('settings.accountSaveFailed')
  } finally {
    busy.value = false
  }
}

function roleLabel(role: string) {
  return role === 'admin' ? t('settings.accountRoleAdmin') : t('settings.accountRoleUser')
}
</script>

<template>
  <section class="card">
    <div class="card-header">
      <h2 class="card-title">{{ t('settings.account') }}</h2>
      <button
        v-if="isAdmin && !loading"
        type="button"
        class="primary-btn"
        :disabled="busy || anyModalOpen"
        @click="openCreate"
      >
        {{ t('settings.accountCreate') }}
      </button>
    </div>

    <p v-if="loading" class="status">{{ t('settings.accountLoading') }}</p>
    <p v-else-if="error" class="status err">{{ error }}</p>
    <p v-else-if="statusMsg" class="status ok">{{ statusMsg }}</p>

    <template v-if="!loading && auth.user">
      <div class="rows">
        <div class="row current-row">
          <div class="current-line">
            <span class="label">{{ t('settings.accountCurrent') }}</span>
            <span class="value">{{ auth.user.username }}</span>
            <span class="role-tag">{{ roleLabel(auth.user.role) }}</span>
          </div>
          <div class="toolbar-actions">
            <button type="button" class="ghost-btn" :disabled="busy" @click="onLogout">
              {{ t('settings.accountLogout') }}
            </button>
            <button
              type="button"
              class="primary-btn"
              :disabled="busy || anyModalOpen"
              @click="openReset"
            >
              {{ t('settings.accountResetPassword') }}
            </button>
          </div>
        </div>
      </div>
    </template>
  </section>

  <Teleport to="body">
    <div
      v-if="resetOpen"
      class="account-modal-root"
      role="dialog"
      aria-modal="true"
      :aria-label="t('settings.accountResetPassword')"
    >
      <div class="account-backdrop" @click="closeReset" />
      <div class="account-modal">
        <div class="account-head">
          <h2>{{ t('settings.accountResetPassword') }}</h2>
          <button type="button" class="account-close" :disabled="busy" @click="closeReset">
            ×
          </button>
        </div>
        <div class="account-body">
          <label class="field">
            <span class="field-label">{{ t('settings.accountOldPassword') }}</span>
            <PasswordInput v-model="oldPassword" autocomplete="current-password" :disabled="busy" />
          </label>
          <label class="field">
            <span class="field-label">{{ t('settings.accountNewPassword') }}</span>
            <PasswordInput
              v-model="newPassword"
              autocomplete="new-password"
              :placeholder="t('settings.accountPasswordPlaceholder')"
              :disabled="busy"
            />
          </label>
          <label class="field">
            <span class="field-label">{{ t('settings.accountConfirmPassword') }}</span>
            <PasswordInput
              v-model="newConfirm"
              autocomplete="new-password"
              :disabled="busy"
              @keyup.enter="onResetPassword"
            />
          </label>
          <p v-if="resetError" class="modal-error">{{ resetError }}</p>
        </div>
        <div class="account-foot">
          <button type="button" class="ghost-btn" :disabled="busy" @click="closeReset">
            {{ t('settings.accountCancel') }}
          </button>
          <button
            type="button"
            class="primary-btn"
            :disabled="busy || !oldPassword || !newPassword"
            @click="onResetPassword"
          >
            {{ t('settings.accountResetPassword') }}
          </button>
        </div>
      </div>
    </div>
  </Teleport>

  <Teleport to="body">
    <div
      v-if="createOpen"
      class="account-modal-root"
      role="dialog"
      aria-modal="true"
      :aria-label="t('settings.accountCreate')"
    >
      <div class="account-backdrop" @click="closeCreate" />
      <div class="account-modal account-modal-wide">
        <div class="account-head">
          <h2>{{ t('settings.accountCreate') }}</h2>
          <button type="button" class="account-close" :disabled="busy" @click="closeCreate">
            ×
          </button>
        </div>
        <div class="account-body create-body">
          <div class="list-block">
            <p class="list-title">{{ t('settings.accountList') }}</p>
            <div class="user-list">
              <div v-for="user in pagedUsers" :key="user.id" class="user-item">
                <div class="user-meta">
                  <span class="value">{{ user.username }}</span>
                  <span class="role-tag">{{ roleLabel(user.role) }}</span>
                  <span v-if="user.disabled" class="role-tag muted">{{ t('settings.accountDisabled') }}</span>
                </div>
                <div class="user-actions">
                  <button type="button" class="link" :disabled="busy" @click="onToggleDisabled(user)">
                    {{ user.disabled ? t('settings.accountEnable') : t('settings.accountDisable') }}
                  </button>
                  <button type="button" class="link" :disabled="busy" @click="onAdminReset(user)">
                    {{ t('settings.accountResetPassword') }}
                  </button>
                  <button
                    type="button"
                    class="icon-action"
                    :title="t('settings.accountDelete')"
                    :disabled="busy"
                    @click="onDelete(user)"
                  >
                    ×
                  </button>
                </div>
              </div>
              <div v-if="!users.length" class="user-item empty">
                <span class="value mute">{{ t('settings.accountEmpty') }}</span>
              </div>
            </div>
            <div v-if="users.length > LIST_PAGE_SIZE" class="list-pager">
              <button
                type="button"
                class="pager-btn"
                :disabled="listPage <= 1"
                @click="listPage -= 1"
              >
                ‹
              </button>
              <span class="pager-info">{{ listPage }} / {{ listPageCount }}</span>
              <button
                type="button"
                class="pager-btn"
                :disabled="listPage >= listPageCount"
                @click="listPage += 1"
              >
                ›
              </button>
            </div>
          </div>

          <div class="form-block">
            <p class="form-title">{{ t('settings.accountCreate') }}</p>
            <label class="field">
              <span class="field-label">{{ t('settings.accountUsername') }}</span>
              <input
                v-model="createUsername"
                class="field-input"
                type="text"
                autocomplete="off"
                maxlength="32"
                :placeholder="t('settings.accountUsernamePlaceholder')"
                :disabled="busy"
              />
            </label>
            <label class="field">
              <span class="field-label">{{ t('settings.accountRole') }}</span>
              <select v-model="createRole" class="role-select" :disabled="busy">
                <option value="user">{{ t('settings.accountRoleUser') }}</option>
                <option value="admin">{{ t('settings.accountRoleAdmin') }}</option>
              </select>
            </label>
            <label class="field">
              <span class="field-label">{{ t('settings.accountPassword') }}</span>
              <PasswordInput
                v-model="createPassword"
                autocomplete="new-password"
                :placeholder="t('settings.accountPasswordPlaceholder')"
                :disabled="busy"
              />
            </label>
            <label class="field">
              <span class="field-label">{{ t('settings.accountConfirmPassword') }}</span>
              <PasswordInput
                v-model="createConfirm"
                autocomplete="new-password"
                :disabled="busy"
                @keyup.enter="onCreate"
              />
            </label>
            <p v-if="createError" class="modal-error">{{ createError }}</p>
          </div>
        </div>
        <div class="account-foot">
          <button type="button" class="ghost-btn" :disabled="busy" @click="closeCreate">
            {{ t('settings.accountCancel') }}
          </button>
          <button
            type="button"
            class="primary-btn"
            :disabled="busy || !createUsername.trim() || !createPassword"
            @click="onCreate"
          >
            {{ t('settings.accountCreate') }}
          </button>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
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

.card-header .primary-btn {
  flex-shrink: 0;
}

.card-title {
  margin: 0;
  font-size: 15px;
  font-weight: 600;
  color: var(--color-text);
}

.status {
  margin: 8px 0 12px;
  font-size: 13px;
  color: var(--color-text-muted);
}

.status.err {
  color: #ef4444;
}

.status.ok {
  color: #22c55e;
}

.rows {
  display: flex;
  flex-direction: column;
}

.row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  min-height: 44px;
  padding: 10px 0;
  font-size: 14px;
  border-top: 1px solid var(--color-border);
}

.rows > .row:first-child {
  border-top: 0;
}

.current-row {
  gap: 12px;
}

.current-line {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  flex: 1;
  flex-wrap: nowrap;
}

.current-line .value {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.toolbar-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}

.label {
  color: var(--color-text-muted);
  flex-shrink: 0;
}

.value {
  color: var(--color-text);
}

.role-tag {
  font-size: 11px;
  padding: 2px 7px;
  border-radius: 999px;
  color: var(--color-text-muted);
  background: color-mix(in srgb, var(--color-accent) 12%, transparent);
}

.role-tag.muted {
  background: var(--color-border);
}

.primary-btn {
  border: 0;
  background: var(--color-accent);
  color: #fff;
  height: 32px;
  padding: 0 14px;
  border-radius: 8px;
  font-size: 13px;
  cursor: pointer;
}

.primary-btn:disabled,
.ghost-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.ghost-btn {
  border: 1px solid var(--color-border);
  background: transparent;
  color: var(--color-text);
  height: 32px;
  padding: 0 14px;
  border-radius: 8px;
  font-size: 13px;
  cursor: pointer;
}

.account-modal-root {
  --modal-accent: var(--color-accent);
  --modal-bg: var(--color-surface);
  --modal-text: var(--color-text);
  --modal-mute: var(--color-text-muted);
  --modal-border: var(--color-border);
  --modal-input-bg: var(--color-bg);
  --modal-list-bg: color-mix(in srgb, var(--color-bg) 80%, var(--color-surface));
  --modal-backdrop: rgba(15, 23, 42, 0.48);
  --modal-shadow: 0 24px 64px rgba(15, 23, 42, 0.22);

  position: fixed;
  inset: 0;
  z-index: 1200;
  display: grid;
  place-items: center;
  padding: 20px;
  color: var(--modal-text);
}

.account-backdrop {
  position: absolute;
  inset: 0;
  background: var(--modal-backdrop);
}

.account-modal {
  position: relative;
  width: min(420px, 100%);
  max-height: min(90vh, 720px);
  overflow: auto;
  border-radius: 12px;
  border: 1px solid var(--modal-border);
  background: var(--modal-bg);
  color: var(--modal-text);
  box-shadow: var(--modal-shadow);
}

.account-modal-wide {
  width: min(640px, 100%);
}

.account-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 14px 16px;
  border-bottom: 1px solid var(--modal-border);
}

.account-head h2 {
  margin: 0;
  font-size: 15px;
  font-weight: 600;
}

.account-close {
  border: 0;
  background: transparent;
  color: var(--modal-mute);
  width: 30px;
  height: 30px;
  border-radius: 8px;
  font-size: 20px;
  line-height: 1;
  cursor: pointer;
}

.account-close:hover:not(:disabled) {
  color: var(--modal-text);
  background: color-mix(in srgb, var(--color-accent) 12%, transparent);
}

.account-body {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 16px;
}

.create-body {
  display: grid;
  grid-template-columns: minmax(220px, 1fr) minmax(240px, 1.1fr);
  gap: 20px;
  align-items: start;
}

.list-block,
.form-block {
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-width: 0;
}

.form-block {
  padding-left: 20px;
  border-left: 1px solid var(--modal-border);
}

.list-title,
.form-title {
  margin: 0;
  font-size: 13px;
  font-weight: 600;
}

.user-list {
  width: 100%;
  max-height: 280px;
  overflow: auto;
  border: 1px solid var(--modal-border);
  border-radius: 10px;
  background: var(--modal-list-bg);
}

.user-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  min-height: 40px;
  padding: 6px 10px;
  border-top: 1px solid var(--modal-border);
}

.user-item:first-child {
  border-top: 0;
}

.user-item.empty {
  justify-content: flex-start;
}

.user-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.user-meta .value {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.value.mute {
  color: var(--modal-mute);
}

.user-actions {
  display: flex;
  align-items: center;
  gap: 2px;
  flex-shrink: 0;
}

.link {
  border: 0;
  background: transparent;
  color: var(--color-accent);
  font-size: 12px;
  padding: 0 6px;
  height: 28px;
  cursor: pointer;
}

.link:disabled,
.icon-action:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.icon-action {
  border: 0;
  background: transparent;
  color: var(--modal-mute);
  width: 28px;
  height: 28px;
  border-radius: 8px;
  font-size: 16px;
  cursor: pointer;
}

.icon-action:hover:not(:disabled) {
  color: #ef4444;
  background: color-mix(in srgb, #ef4444 12%, transparent);
}

.list-pager {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding-top: 2px;
}

.pager-btn {
  width: 28px;
  height: 28px;
  border: 1px solid var(--modal-border);
  border-radius: 8px;
  background: var(--modal-input-bg);
  color: var(--modal-text);
  cursor: pointer;
}

.pager-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.pager-info {
  min-width: 48px;
  text-align: center;
  font-size: 12px;
  color: var(--modal-mute);
}

.field {
  display: flex;
  flex-direction: column;
  gap: 6px;
  width: 100%;
}

.field-label {
  font-size: 13px;
  font-weight: 500;
}

.field-input,
.role-select {
  width: 100%;
  max-width: 240px;
  height: 36px;
  padding: 0 12px;
  border: 1.5px solid var(--modal-border);
  border-radius: 8px;
  background: var(--modal-input-bg);
  color: var(--modal-text);
  font-size: 14px;
  outline: none;
  box-sizing: border-box;
}

.role-select {
  width: 140px;
}

.field-input:focus,
.role-select:focus {
  border-color: var(--color-accent);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--color-accent) 22%, transparent);
}

.modal-error {
  margin: 0;
  font-size: 13px;
  color: #ef4444;
}

.account-foot {
  display: flex;
  justify-content: flex-end;
  align-items: center;
  gap: 10px;
  padding: 12px 16px 16px;
  border-top: 1px solid var(--modal-border);
}

.account-modal-root .primary-btn {
  background: var(--color-accent);
}

.account-modal-root .ghost-btn {
  border-color: var(--modal-border);
  color: var(--modal-text);
}

@media (max-width: 640px) {
  .current-row {
    flex-wrap: wrap;
  }

  .create-body {
    grid-template-columns: 1fr;
  }

  .form-block {
    padding-left: 0;
    border-left: 0;
    padding-top: 12px;
    border-top: 1px solid var(--modal-border);
  }
}
</style>
