/** 工作区产物路径分流：表格 / Markdown / 图片 / 纯文本 */

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
  return `/api/workspace/media?${q}`
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
  return html.join('\n')
}
