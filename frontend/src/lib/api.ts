import { InteractionRequiredAuthError } from '@azure/msal-browser'

import { loginRequest, msalInstance } from './msal'

async function getAccessToken(): Promise<string | null> {
  const account = msalInstance.getActiveAccount()
  if (!account) return null

  try {
    const result = await msalInstance.acquireTokenSilent({ ...loginRequest, account })
    return result.accessToken
  } catch (err) {
    if (err instanceof InteractionRequiredAuthError) {
      const result = await msalInstance.acquireTokenPopup(loginRequest)
      return result.accessToken
    }
    throw err
  }
}

export async function apiFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = await getAccessToken()

  // FormData must set its own Content-Type — it carries a generated
  // multipart boundary, and overriding it makes the body unparseable.
  const isFormData = init.body instanceof FormData

  const res = await fetch(`/api${path}`, {
    ...init,
    headers: {
      ...(isFormData ? {} : { 'Content-Type': 'application/json' }),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...init.headers,
    },
  })

  if (!res.ok) {
    // FastAPI reports errors as {"detail": ...}; surface that rather than
    // raw JSON, since these strings get shown to the user directly.
    const body = await res.text()
    let message = body
    try {
      const parsed = JSON.parse(body)
      if (typeof parsed.detail === 'string') message = parsed.detail
      else if (Array.isArray(parsed.detail)) message = parsed.detail[0]?.msg ?? body
    } catch {
      // not JSON — fall back to the raw body
    }
    throw new Error(message || `${res.status} ${res.statusText}`)
  }

  if (res.status === 204) return undefined as T
  return res.json() as Promise<T>
}

/**
 * Fetch a binary endpoint (PDF, crop image) as an object URL.
 *
 * These endpoints require a bearer token, so they can't be opened by
 * pointing the browser at the URL directly — a plain window.open sends no
 * Authorization header and gets a 401. Fetch it properly, then hand back
 * a blob URL the browser can display.
 *
 * Callers must revokeObjectURL when done, or the blob leaks for the life
 * of the page.
 */
export async function apiFetchBlobUrl(path: string): Promise<string> {
  const token = await getAccessToken()
  const res = await fetch(`/api${path}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  })
  if (!res.ok) {
    throw new Error(`${res.status} ${res.statusText}`)
  }
  return URL.createObjectURL(await res.blob())
}
