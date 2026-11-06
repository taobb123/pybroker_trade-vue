/** 工作区产物路径分流：表格 / Markdown / 图片 / 纯文本 */

import { apiUrl } from '@/config/apiBase'

export function workspacePathSuffix(relPath: string): string {
  let s = String(relPath || '').toLowerCase()
  const q = s.indexOf('?')
  if (q >= 0) s = s.slice(0, q)
  const i = s.lastIndexOf('.')
  return i >= 0 ? s.slice(i) : ''
}

export function isImageWorkspacePath(relPath: string): boolean {
  return ['.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg'].includes(
    workspacePathSuffix(relPath),
  )
}

export function isMarkdownWorkspacePath(relPath: string): boolean {
  return ['.md', '.markdown'].includes(workspacePathSuffix(relPath))
}

export function isTextWorkspacePath(relPath: string): boolean {
  return workspacePathSuffix(relPath) === '.txt'
}

export function workspaceMediaUrl(relPath: string, bust = true): string {
  const q = new URLSearchParams({ path: relPath })
  if (bust) q.set('_t', String(Date.now()))
  return apiUrl(`/api/workspace/media?${q}`)
}

function escapeHtmlText(s: string): string {
  return String(s ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}

function renderInlineMd(text: string): string {
  let s = escapeHtmlText(text)
  s = s.replace(/`([^`]+)`/g, '<code>$1</code>')
  s = s.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
  s = s.replace(
    /\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g,
    '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>',
  )
  return s
}

function isMdTableSeparator(line: string): boolean {
  return /^\s*\|?[\s:-]+\|[\s|:-]*$/.test(line)
}

function splitMdTableRow(line: string): string[] {
  let s = String(line || '').trim()
  if (s.startsWith('|')) s = s.slice(1)
  if (s.endsWith('|')) s = s.slice(0, -1)
  return s.split('|').map((c) => c.trim())
}

const DAILY_BRIEF_SECTIONS = [
  '行情 KPI',
  '连板天梯前三档',
  '涨停家数最多的三个题材',
  '龙虎榜净买额前五',
] as const

const LEADER_SECTION = '每日龙头切换'

export function isDailyBriefMarkdown(src: string): boolean {
  const text = String(src || '')
  if (!text.includes('A股复盘简报')) return false
  return DAILY_BRIEF_SECTIONS.every((title) => text.includes(`## ${title}`))
}

function compactLhbTable(body: string): string {
  const match = body.match(/<table>[\s\S]*?<\/table>/)
  if (!match) return body
  const tbody = match[0].match(/<tbody>([\s\S]*?)<\/tbody>/)
  if (!tbody?.[1]) return body
  const items: string[] = []
  const trRe = /<tr>([\s\S]*?)<\/tr>/g
  let tr: RegExpExecArray | null
  while ((tr = trRe.exec(tbody[1]))) {
    const cells: string[] = []
    const cellRe = /<td>([\s\S]*?)<\/td>/g
    let cell: RegExpExecArray | null
    while ((cell = cellRe.exec(tr[1] ?? ''))) cells.push(cell[1] ?? '')
    if (cells.length < 6) continue
    const seat = cells[5]
    const seatText = seat && seat !== '—' ? ` · ${seat}` : ''
    items.push(
      `<li><div class="brief-lhb-line"><span class="brief-stock">${cells[2]}</span><span class="brief-num">${cells[3]}</span><span class="brief-num">${cells[4]}</span></div><div class="brief-lhb-seat">${cells[0]} · ${cells[1]}${seatText}</div></li>`,
    )
  }
  if (!items.length) return body
  return body.replace(match[0], `<ol class="brief-lhb">${items.join('')}</ol>`)
}

function emphasizeLogicItem(text: string): string {
  const bar = text.indexOf('｜')
  const head = (bar >= 0 ? text.slice(0, bar) : text).trim()
  const news = bar >= 0 ? text.slice(bar + 1).trim() : ''
  const matched = head.match(/^(.+?)\s*[—\-]\s*(.+)$/)
  const body = matched
    ? `<b class="brief-theme">${matched[1]}</b><span class="brief-logic-title">${matched[2]}</span>`
    : `<b class="brief-theme">${head}</b>`
  const newsHtml = news ? `<span class="brief-logic-news">${news}</span>` : ''
  return body + newsHtml
}

function kpiDownClass(label: string, value: string): string {
  const name = label.replace(/<[^>]+>/g, '').trim()
  const text = value.replace(/<[^>]+>/g, '').trim()
  if (name.includes('炸板')) return ' brief-down'
  const numeric = Number(text.replace(/,/g, '').replace(/%|板|万亿|亿|万|元|\+/g, ''))
  if (text.startsWith('-') || text.startsWith('−') || (Number.isFinite(numeric) && numeric < 0)) {
    return ' brief-down'
  }
  return ''
}

function decorateKpiExtras(body: string): string {
  let next = body.replace(/<p>([\s\S]*?)<\/p>/, (full, inner: string) => {
    const text = inner.replace(/<[^>]+>/g, '')
    if (!text.includes('上证') || !text.includes('深证')) return full
    const bits = text.split('、').map((bit) => {
      const piece = bit.trim().match(/^(\S+)\s+([+\-]?\d+(?:\.\d+)?%)$/)
      if (!piece) return ''
      const down = piece[2].startsWith('-') ? ' brief-down' : ''
      return `<span class="brief-index"><span>${piece[1]}</span><b class="${down.trim()}">${piece[2]}</b></span>`
    })
    return `<p class="brief-indices">${bits.join('')}</p>`
  })
  next = next.replace(
    /<li>([\s\S]*?)<\/li>/g,
    (_, inner: string) => `<li class="brief-logic">${emphasizeLogicItem(inner)}</li>`,
  )
  return next
}

function emphasizeKpi(body: string): string {
  const rows: string[] = []
  const re = /<tr>\s*<td>([\s\S]*?)<\/td>\s*<td>([\s\S]*?)<\/td>\s*<\/tr>/g
  let match: RegExpExecArray | null
  while ((match = re.exec(body))) {
    rows.push(
      `<div class="brief-kpi-tile"><span class="brief-kpi">${match[1]}</span><span class="brief-kpi-value${kpiDownClass(match[1] ?? '', match[2] ?? '')}">${match[2]}</span></div>`,
    )
  }
  const withTiles = rows.length
    ? body.replace(/<table>[\s\S]*?<\/table>/, `<div class="brief-kpi-row">${rows.join('')}</div>`)
    : body
  return decorateKpiExtras(withTiles)
}

function emphasizeLadderItem(text: string): string {
  const matched = text.match(/^([\s\S]*?)（([^）]*)）\s*$/)
  if (!matched) return `<span class="brief-stock">${text}</span>`
  const head = matched[1] ?? ''
  const theme = matched[2] ?? ''
  const dot = head.indexOf(' · ')
  const stock = dot >= 0 ? head.slice(0, dot) : head
  const rest = dot >= 0 ? head.slice(dot) : ''
  const rhythm = rest ? `<span class="brief-rhythm">${rest.replace(/^ · /, '')}</span>` : ''
  const tag = theme ? `<span class="brief-theme">${theme}</span>` : ''
  return `<span class="brief-stock">${stock}</span>${rhythm}${tag}`
}

function emphasizeThemeItem(text: string): string {
  const matched = text.trim().match(/^(.+?)\s*[—\-]\s*(.+)$/)
  if (!matched) return `<b class="brief-theme">${text}</b>`
  return `<b class="brief-theme">${matched[1]}</b><span class="brief-count">${matched[2]}</span>`
}

function markBoardHeads(body: string): string {
  return body.replace(/<h3>([\s\S]*?)<\/h3>/g, (_, inner: string) => {
    const text = String(inner).replace(/<[^>]+>/g, '')
    const matched = text.match(/^(.+?)（(.+?)）\s*$/)
    if (!matched) return `<h3 class="brief-board-tier"><span class="brief-tier">${inner}</span></h3>`
    return `<h3 class="brief-board-tier"><span class="brief-tier">${matched[1]}</span><span class="brief-count">${matched[2]}</span></h3>`
  })
}

function emphasizeLadder(body: string): string {
  const chips = body.replace(
    /<li>([\s\S]*?)<\/li>/g,
    (_, inner: string) => `<li class="brief-chip">${emphasizeLadderItem(inner)}</li>`,
  )
  return markBoardHeads(chips)
}

function emphasizeThemes(body: string): string {
  return body.replace(
    /<li>([\s\S]*?)<\/li>/g,
    (_, inner: string) => `<li class="brief-theme-row">${emphasizeThemeItem(inner)}</li>`,
  )
}

function parseLeaderLine(text: string): { label: string; body: string } | null {
  const matched = text.trim().match(/^(今日|昨日(?:（[^）]*）)?|切换)：\s*(.*)$/)
  if (!matched) return null
  let label = matched[1] ?? ''
  const dated = label.match(/^昨日（(.+)）$/)
  if (dated) label = `昨日 ${dated[1]}`
  return { label, body: (matched[2] ?? '').trim() }
}

function leaderSwitchHtml(body: string): string {
  const legacy = body.match(/^龙头\s+(.+?)\s+切换\s+(.+)$/)
  const arrow = body.match(/^(.+?)\s*(?:→|->)\s*(.+)$/)
  const pair = legacy || arrow
  if (pair?.[1] && pair[2]) {
    return `<span class="brief-leader-flow"><span class="brief-kpi-value">${escapeHtmlText(pair[1])}</span><span class="brief-leader-arrow">→</span><span class="brief-kpi-value">${escapeHtmlText(pair[2])}</span></span>`
  }
  const stay = body.match(/^(?:龙头\s+)?(.+?)\s+未切换$/)
  if (stay?.[1]) {
    return `<span class="brief-kpi-value">${escapeHtmlText(stay[1])}</span><span class="brief-theme">未切换</span>`
  }
  return `<span class="brief-stock">${escapeHtmlText(body)}</span>`
}

function leaderValueHtml(label: string, body: string): string {
  if (label === '切换') return leaderSwitchHtml(body)
  const named = body.match(/^(.+?)（([^）]+)）$/)
  if (named?.[1]) {
    return `<span class="brief-kpi-value">${escapeHtmlText(named[1])}</span><span class="brief-theme">${escapeHtmlText(named[2] ?? '')}</span>`
  }
  return `<span class="brief-kpi-value">${escapeHtmlText(body)}</span>`
}

function emphasizeLeader(body: string): string {
  const tiles: string[] = []
  const re = /<li>([\s\S]*?)<\/li>/g
  let match: RegExpExecArray | null
  while ((match = re.exec(body))) {
    const text = String(match[1] ?? '').replace(/<[^>]+>/g, '')
    const parsed = parseLeaderLine(text)
    if (!parsed) continue
    tiles.push(
      `<div class="brief-kpi-tile"><span class="brief-kpi">${escapeHtmlText(parsed.label)}</span>${leaderValueHtml(parsed.label, parsed.body)}</div>`,
    )
  }
  if (!tiles.length) return body
  return body.replace(/<ul>[\s\S]*?<\/ul>/, `<div class="brief-leader-row">${tiles.join('')}</div>`)
}

function peelBriefFoot(body: string): { body: string; foot: string[] } {
  const chunks = body.split(/(?=<p>)/)
  const bodyChunks: string[] = []
  const foot: string[] = []
  for (const chunk of chunks) {
    if (chunk.startsWith('<p>原文：') || chunk.startsWith('<p>数据来源：')) foot.push(chunk)
    else bodyChunks.push(chunk)
  }
  return { body: bodyChunks.join(''), foot }
}

/** 收盘简报分段排布。其它 Markdown 原样返回。 */
export function layoutDailyBriefHtml(html: string): string {
  if (!html.includes('A股复盘简报')) return html
  const parts = html.split('<h2>')
  if (parts.length < 5) return html
  const sections: { title: string; plain: string; body: string }[] = []
  for (let i = 1; i < parts.length; i += 1) {
    const chunk = parts[i] ?? ''
    const end = chunk.indexOf('</h2>')
    if (end < 0) return html
    const title = chunk.slice(0, end)
    sections.push({
      title,
      plain: title.replace(/<[^>]+>/g, ''),
      body: chunk.slice(end + 5),
    })
  }
  const byPlain = new Map(sections.map((section) => [section.plain, section]))
  if (!DAILY_BRIEF_SECTIONS.every((title) => byPlain.has(title))) return html
  const kpi = byPlain.get('行情 KPI')
  const ladder = byPlain.get('连板天梯前三档')
  const themes = byPlain.get('涨停家数最多的三个题材')
  const lhb = byPlain.get('龙虎榜净买额前五')
  if (!kpi || !ladder || !themes || !lhb) return html
  const peeled = peelBriefFoot(lhb.body)
  lhb.body = compactLhbTable(peeled.body)
  const known = new Set<string>([...DAILY_BRIEF_SECTIONS, LEADER_SECTION])
  const extra = sections
    .filter((section) => !known.has(section.plain))
    .map((section) => `<h2>${section.title}</h2>${section.body}`)
    .join('')
  const panel = (title: string, body: string, extraClass = '') =>
    `<section class="brief-panel${extraClass}"><h2>${title}</h2>${body}</section>`
  const leader = byPlain.get(LEADER_SECTION)
  const leaderHtml = leader
    ? panel(leader.title, emphasizeLeader(leader.body), ' brief-leader')
    : ''
  return `<div class="brief-board"><div class="brief-head">${parts[0] ?? ''}</div>${panel(kpi.title, emphasizeKpi(kpi.body), ' brief-kpis')}${leaderHtml}<div class="brief-split">${panel(ladder.title, emphasizeLadder(ladder.body), ' brief-ladder')}<div class="brief-side">${panel(themes.title, emphasizeThemes(themes.body))}${panel(lhb.title, lhb.body, ' brief-lhb-panel')}</div></div><div class="brief-foot">${peeled.foot.join('')}${extra}</div></div>`
}

/** 轻量 Markdown → HTML（与 stock_pool_workflow.html 对齐，先转义再内联） */
export function renderMarkdownToHtml(src: string): string {
  const lines = String(src || '')
    .replace(/\r\n/g, '\n')
    .split('\n')
  const html: string[] = []
  let i = 0
  let inCode = false
  const codeBuf: string[] = []
  let listType: '' | 'ul' | 'ol' = ''

  const closeList = () => {
    if (listType === 'ul') html.push('</ul>')
    if (listType === 'ol') html.push('</ol>')
    listType = ''
  }

  while (i < lines.length) {
    const line = lines[i] ?? ''

    if (inCode) {
      if (/^```/.test(line)) {
        html.push(`<pre><code>${escapeHtmlText(codeBuf.join('\n'))}</code></pre>`)
        codeBuf.length = 0
        inCode = false
        i += 1
        continue
      }
      codeBuf.push(line)
      i += 1
      continue
    }

    if (/^```/.test(line)) {
      closeList()
      inCode = true
      i += 1
      continue
    }

    if (/^\s*---+\s*$/.test(line) || /^\s*\*\*\*+\s*$/.test(line)) {
      closeList()
      html.push('<hr/>')
      i += 1
      continue
    }

    const hm = /^(#{1,3})\s+(.+)$/.exec(line)
    if (hm) {
      closeList()
      const level = hm[1]!.length
      html.push(`<h${level}>${renderInlineMd(hm[2]!)}</h${level}>`)
      i += 1
      continue
    }

    if (
      line.includes('|') &&
      i + 1 < lines.length &&
      isMdTableSeparator(lines[i + 1] ?? '')
    ) {
      closeList()
      const headers = splitMdTableRow(line)
      i += 2
      const rows: string[][] = []
      while (i < lines.length && (lines[i] ?? '').includes('|') && String(lines[i]).trim()) {
        if (isMdTableSeparator(lines[i] ?? '')) {
          i += 1
          continue
        }
        rows.push(splitMdTableRow(lines[i] ?? ''))
        i += 1
      }
      html.push('<table><thead><tr>')
      headers.forEach((h) => {
        html.push(`<th>${renderInlineMd(h)}</th>`)
      })
      html.push('</tr></thead><tbody>')
      rows.forEach((row) => {
        html.push('<tr>')
        headers.forEach((_h, idx) => {
          html.push(`<td>${renderInlineMd(row[idx] || '')}</td>`)
        })
        html.push('</tr>')
      })
      html.push('</tbody></table>')
      continue
    }

    const ul = /^\s*[-*+]\s+(.+)$/.exec(line)
    if (ul) {
      if (listType !== 'ul') {
        closeList()
        html.push('<ul>')
        listType = 'ul'
      }
      html.push(`<li>${renderInlineMd(ul[1]!)}</li>`)
      i += 1
      continue
    }

    const ol = /^\s*\d+\.\s+(.+)$/.exec(line)
    if (ol) {
      if (listType !== 'ol') {
        closeList()
        html.push('<ol>')
        listType = 'ol'
      }
      html.push(`<li>${renderInlineMd(ol[1]!)}</li>`)
      i += 1
      continue
    }

    if (!String(line).trim()) {
      closeList()
      i += 1
      continue
    }

    closeList()
    html.push(`<p>${renderInlineMd(line)}</p>`)
    i += 1
  }

  closeList()
  if (inCode) {
    html.push(`<pre><code>${escapeHtmlText(codeBuf.join('\n'))}</code></pre>`)
  }
  return layoutDailyBriefHtml(html.join('\n'))
}
