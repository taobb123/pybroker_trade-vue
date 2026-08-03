export type PlanTier = 'free' | 'pro' | 'team'

export type ServerUser = {
  id: string
  email: string
  nickname: string
  phone: string
  avatar_text: string
  role: string
  status: string
  onboarding_done: boolean
  persona: string | null
  invite_code: string
  plan: PlanTier
  expire_at: string | null
  created_at: string
  last_login_at: string | null
}

const TOKEN_KEY = 'workflow-platform:auth-token:v1'

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY)
}

export function setToken(token: string | null) {
  if (!token) localStorage.removeItem(TOKEN_KEY)
  else localStorage.setItem(TOKEN_KEY, token)
}

async function readError(res: Response): Promise<string> {
  try {
    const j = (await res.json()) as { detail?: string }
    if (typeof j.detail === 'string') return j.detail
  } catch {
    /* ignore */
  }
  if (res.status === 404) {
    return '接口不存在（404）。请重启 workflow_server 后再登录'
  }
  return `HTTP ${res.status}`
}

function authHeaders(): HeadersInit {
  const t = getToken()
  return t ? { Authorization: `Bearer ${t}` } : {}
}

export async function apiRegister(input: {
  email: string
  password: string
  nickname?: string
  phone?: string
}): Promise<{ token: string; user: ServerUser }> {
  const res = await fetch('/api/auth/register', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
  })
  if (!res.ok) throw new Error(await readError(res))
  const j = (await res.json()) as { token: string; user: ServerUser }
  return j
}

export async function apiLogin(input: {
  email: string
  password: string
}): Promise<{ token: string; user: ServerUser }> {
  const res = await fetch('/api/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
  })
  if (!res.ok) throw new Error(await readError(res))
  return (await res.json()) as { token: string; user: ServerUser }
}

export async function apiMe(): Promise<ServerUser> {
  const res = await fetch('/api/auth/me', { headers: { ...authHeaders() } })
  if (!res.ok) throw new Error(await readError(res))
  const j = (await res.json()) as { user: ServerUser }
  return j.user
}

export async function apiPatchMe(input: {
  nickname?: string
  phone?: string
}): Promise<ServerUser> {
  const res = await fetch('/api/auth/me', {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify(input),
  })
  if (!res.ok) throw new Error(await readError(res))
  const j = (await res.json()) as { user: ServerUser }
  return j.user
}
