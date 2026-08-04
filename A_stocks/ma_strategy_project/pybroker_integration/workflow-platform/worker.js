/**
 * Cloudflare Worker：静态站 + 同源反代 /api → 香港后端
 * 手机流量只需访问 freealpha.lol，不再直连 api. 子域（国内蜂窝更稳）
 */
const DEFAULT_API_ORIGIN = 'https://api.freealpha.lol'

export default {
  async fetch(request, env) {
    const url = new URL(request.url)

    if (url.pathname === '/api' || url.pathname.startsWith('/api/')) {
      const origin = String(env.API_ORIGIN || DEFAULT_API_ORIGIN).replace(/\/+$/, '')
      const target = new URL(url.pathname + url.search, origin + '/')

      const headers = new Headers(request.headers)
      headers.delete('host')
      // 避免把浏览端 CF 头原样传乱；保留 Authorization / Content-Type
      headers.set('x-forwarded-host', url.host)
      headers.set('x-forwarded-proto', 'https')

      /** @type {RequestInit} */
      const init = {
        method: request.method,
        headers,
        redirect: 'manual',
      }
      if (request.method !== 'GET' && request.method !== 'HEAD') {
        init.body = request.body
        // Workers 流式 body 需要 duplex
        // @ts-expect-error
        init.duplex = 'half'
      }

      try {
        return await fetch(target.toString(), init)
      } catch (err) {
        return new Response(
          JSON.stringify({
            detail: 'upstream api unreachable',
            error: String(err),
          }),
          {
            status: 502,
            headers: { 'content-type': 'application/json; charset=utf-8' },
          },
        )
      }
    }

    // SPA 静态资源
    if (env.ASSETS) {
      return env.ASSETS.fetch(request)
    }
    return new Response('ASSETS binding missing', { status: 500 })
  },
}
