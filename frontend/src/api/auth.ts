import { api } from '@/api'

export interface UserPublic {
  id: string
  username: string
  role: string
  disabled: boolean
  created_at: string
}

export interface AuthStatus {
  setup_required: boolean
  user?: UserPublic | null
}

export interface LoginResult {
  token: string
  user: UserPublic
}

export function fetchAuthStatus() {
  return api.get<AuthStatus>('/auth/status')
}

export function login(username: string, password: string) {
  return api.post<LoginResult>('/auth/login', { username, password })
}

export function changePassword(oldPassword: string, newPassword: string) {
  return api.put<{ ok: boolean }>('/auth/password', {
    old_password: oldPassword,
    new_password: newPassword,
  })
}

export function fetchUsers() {
  return api.get<{ users: UserPublic[] }>('/users')
}

export function createUser(username: string, password: string, role: 'admin' | 'user' = 'user') {
  return api.post<UserPublic>('/users', { username, password, role })
}

export function patchUser(id: string, payload: { disabled: boolean }) {
  return api.patch<UserPublic>(`/users/${id}`, payload)
}

export function adminSetPassword(id: string, newPassword: string) {
  return api.put<{ ok: boolean }>(`/users/${id}/password`, { new_password: newPassword })
}

export function deleteUser(id: string) {
  return api.delete<{ ok: boolean }>(`/users/${id}`)
}
