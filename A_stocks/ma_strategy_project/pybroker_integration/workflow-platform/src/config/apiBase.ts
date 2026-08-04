/**
 * API 根地址：
 * - 本地开发：留空，走相对路径 `/api`（Vite proxy → 8765）
 * - 线上推荐：留空，走同源 `/api`（Cloudflare Worker 反代到香港后端；国内手机更稳）
 * - 可选：构建时设 VITE_API_BASE_URL=https://api.xxx（直连 API 子域，部分蜂窝网络不稳定）
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
