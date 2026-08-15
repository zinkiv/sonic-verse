const TOKEN_KEY = 'sonicverse-auth-token'
const COOKIE_NAME = 'sv_token'

export function getAuthToken(): string {
  return localStorage.getItem(TOKEN_KEY) || ''
}

export function setAuthToken(token: string) {
  if (token) {
    localStorage.setItem(TOKEN_KEY, token)
    document.cookie = `${COOKIE_NAME}=${encodeURIComponent(token)}; Path=/; SameSite=Lax`
  } else {
    clearAuthToken()
  }
}

export function clearAuthToken() {
  localStorage.removeItem(TOKEN_KEY)
  document.cookie = `${COOKIE_NAME}=; Path=/; Max-Age=0`
}
