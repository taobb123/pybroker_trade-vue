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

function emphasizeKpi(body: string): string {
  const rows: string[] = []
  const re = /<tr>\s*<td>([\s\S]*?)<\/td>\s*<td>([\s\S]*?)<\/td>\s*<\/tr>/g
  let match: RegExpExecArray | null
  while ((match = re.exec(body))) {
    rows.push(
      `<div class="brief-kpi-tile"><span class="brief-kpi">${match[1]}</span><span class="brief-kpi-value">${match[2]}</span></div>`,
    )
  }
  if (!rows.length) return body
  return body.replace(/<table>[\s\S]*?<\/table>/, `<div class="brief-kpi-row">${rows.join('')}</div>`)
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

function emphasizeSection(index: number, body: string): string {
  if (index === 0) return emphasizeKpi(body)
  if (index === 1) {
    const chips = body.replace(
      /<li>([\s\S]*?)<\/li>/g,
      (_, inner: string) => `<li class="brief-chip">${emphasizeLadderItem(inner)}</li>`,
    )
    return markBoardHeads(chips)
  }
  if (index === 2) {
    return body.replace(
      /<li>([\s\S]*?)<\/li>/g,
      (_, inner: string) => `<li class="brief-theme-row">${emphasizeThemeItem(inner)}</li>`,
    )
  }
  return body
}

/** 收盘简报四段并排。其它 Markdown 原样返回。 */
export function layoutDailyBriefHtml(html: string): string {
  if (!html.includes('A股复盘简报')) return html
  const parts = html.split('<h2>')
  if (parts.length < 5) return html
  const sections: { title: string; body: string }[] = []
  for (let i = 1; i < parts.length; i += 1) {
    const chunk = parts[i] ?? ''
    const end = chunk.indexOf('</h2>')
    if (end < 0) return html
    sections.push({ title: chunk.slice(0, end), body: chunk.slice(end + 5) })
  }
  if (sections.length < 4) return html
  for (let i = 0; i < DAILY_BRIEF_SECTIONS.length; i += 1) {
    const plain = (sections[i]?.title ?? '').replace(/<[^>]+>/g, '')
    if (plain !== DAILY_BRIEF_SECTIONS[i]) return html
  }
  const last = sections[3]
  if (!last) return html
  const chunks = last.body.split(/(?=<p>)/)
  const bodyChunks: string[] = []
  const footPs: string[] = []
  for (const chunk of chunks) {
    if (chunk.startsWith('<p>原文：') || chunk.startsWith('<p>数据来源：')) footPs.push(chunk)
    else bodyChunks.push(chunk)
  }
  last.body = compactLhbTable(bodyChunks.join(''))
  const bodies = sections.slice(0, 4).map((section, index) => emphasizeSection(index, section.body))
  const panel = (title: string, body: string, extra = '') =>
    `<section class="brief-panel${extra}"><h2>${title}</h2>${body}</section>`
  const extra = sections
    .slice(4)
    .map((section) => `<h2>${section.title}</h2>${section.body}`)
    .join('')
  return `<div class="brief-board"><div class="brief-head">${parts[0] ?? ''}</div>${panel(sections[0]?.title ?? '', bodies[0] ?? '', ' brief-kpis')}<div class="brief-split">${panel(sections[1]?.title ?? '', bodies[1] ?? '', ' brief-ladder')}<div class="brief-side">${panel(sections[2]?.title ?? '', bodies[2] ?? '')}${panel(sections[3]?.title ?? '', bodies[3] ?? '', ' brief-lhb-panel')}</div></div><div class="brief-foot">${footPs.join('')}${extra}</div></div>`
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
