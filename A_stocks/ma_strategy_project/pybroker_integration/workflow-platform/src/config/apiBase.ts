/**
 * API 根地址：
 * - 本地开发：留空，走相对路径 `/api`（Vite proxy → 8765）
 * - 线上：留空，走同源 `/api`（Worker 反代）。跑步骤用 async+轮询，避免 Worker/直连超时。
 * - 可选：VITE_API_BASE_URL=https://api.xxx 强制直连
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
