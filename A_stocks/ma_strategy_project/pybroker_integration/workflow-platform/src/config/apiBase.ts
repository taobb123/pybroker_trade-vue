/**
 * API 根地址：
 * - 本地开发：留空，走相对路径 `/api`（Vite proxy → 8765）
 * - 线上：构建时设 VITE_API_BASE_URL=https://你的后端域名（无尾斜杠）
 */
const RAW = String(import.meta.env.VITE_API_BASE_URL ?? '').trim()

export function apiBase(): string {
  return RAW.replace(/\/+$/, '')
}

/** 把 `/api/...` 拼成最终请求 URL */
export function apiUrl(path: string): string {
  const p = path.startsWith('/') ? path : `/${path}`
  const base = apiBase()
  return base ? `${base}${p}` : p
}
