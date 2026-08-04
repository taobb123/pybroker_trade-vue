/**
 * API 根地址：
 * - 本地开发：留空，走相对路径 `/api`（Vite proxy → 8765）
 * - 线上推荐：留空，登录/配额走同源 `/api`（Worker 反代；国内手机更稳）
 * - 跑步骤 / 工作区：默认直连 VITE_API_RUN_BASE_URL 或 https://api.freealpha.lol
 *   （避免 Cloudflare Worker 反代长任务超时后前端误显示 mock）
 */
const RAW = String(import.meta.env.VITE_API_BASE_URL ?? '').trim()
// 生产默认直连 API 域名跑长任务；本地开发默认空（走 Vite /api 代理）
const RAW_RUN = String(
  import.meta.env.VITE_API_RUN_BASE_URL ??
    (import.meta.env.PROD ? 'https://api.freealpha.lol' : ''),
).trim()

export function apiBase(): string {
  return RAW.replace(/\/+$/, '')
}

export function apiRunBase(): string {
  // 本地未设时：与 apiBase 一致（相对 /api → Vite 代理）
  if (!RAW_RUN && !RAW) return ''
  if (!RAW_RUN) return apiBase()
  return RAW_RUN.replace(/\/+$/, '')
}

/** 把 `/api/...` 拼成最终请求 URL（登录、配额、配置等短请求） */
export function apiUrl(path: string): string {
  const p = path.startsWith('/') ? path : `/${path}`
  const base = apiBase()
  return base ? `${base}${p}` : p
}

/** 跑步骤 / 停止 / 工作区产物（可能较长，线上直连 API 域名） */
export function apiRunUrl(path: string): string {
  const p = path.startsWith('/') ? path : `/${path}`
  const base = apiRunBase()
  return base ? `${base}${p}` : p
}
