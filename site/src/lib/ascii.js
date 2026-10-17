// Grid utilities for parametric ASCII scenes.
// Every scene is a fixed-size grid (w × h) so acts can dissolve into
// each other with per-cell dithering while scroll drives the parameters.

export const makeGrid = (w, h) => {
  const rows = []
  for (let y = 0; y < h; y++) rows.push(new Array(w).fill(' '))
  return rows
}

export const toString = grid => grid.map(r => r.join('')).join('\n')

export const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v))
export const lerp = (a, b, t) => a + (b - a) * clamp(t, 0, 1)

/** Deterministic hash noise in [0, 1) for dithering. */
export const noise = (x, y) => {
  const s = Math.sin(x * 127.1 + y * 311.7) * 43758.5453
  return s - Math.floor(s)
}

/** Write a single-line string into the grid at (x, y), clipped. */
export const put = (grid, x, y, text) => {
  if (y < 0 || y >= grid.length) return grid
  for (let i = 0; i < text.length; i++) {
    const px = x + i
    if (px < 0 || px >= grid[y].length) continue
    grid[y][px] = text[i]
  }
  return grid
}

/** Write multiple lines (array or \n string) at (x, y). */
export const putLines = (grid, x, y, text) => {
  const lines = Array.isArray(text) ? text : text.split('\n')
  lines.forEach((l, i) => put(grid, x, y + i, l))
  return grid
}

/** Horizontal rule of `ch` from x0..x1 inclusive. */
export const rule = (grid, x0, x1, y, ch = '─') => {
  if (y < 0 || y >= grid.length) return grid
  for (let x = Math.max(0, x0); x <= Math.min(grid[y].length - 1, x1); x++) grid[y][x] = ch
  return grid
}

/**
 * Draw a box without a title. Corners ┌ ┐ └ ┘, returns nothing.
 * (Titles are drawn separately with `put` so they can scroll/clip freely.)
 */
export const box = (grid, x0, y0, x1, y1) => {
  rule(grid, x0 + 1, x1 - 1, y0, '─')
  rule(grid, x0 + 1, x1 - 1, y1, '─')
  for (let y = y0 + 1; y < y1; y++) {
    if (grid[y] && x0 >= 0 && x0 < grid[y].length) grid[y][x0] = '│'
    if (grid[y] && x1 >= 0 && x1 < grid[y].length) grid[y][x1] = '│'
  }
  const set = (x, y, ch) => {
    if (grid[y] && x >= 0 && x < grid[y].length) grid[y][x] = ch
  }
  set(x0, y0, '┌'); set(x1, y0, '┐'); set(x0, y1, '└'); set(x1, y1, '┘')
  return grid
}

/** Crop a sub-grid (for reveal effects). */
export const cropRow = (grid, y, x0, x1) => {
  if (!grid[y]) return ''
  return grid[y].slice(Math.max(0, x0), Math.max(0, x1)).join('')
}

/** Per-cell dissolve: returns text that blends gridA into gridB by `mix` (0..1). */
export const dissolve = (gridA, gridB, mix, seed = 0) => {
  const h = Math.max(gridA.length, gridB.length)
  const lines = []
  for (let y = 0; y < h; y++) {
    let line = ''
    const ra = gridA[y] || []
    const rb = gridB[y] || []
    for (let x = 0; x < Math.max(ra.length, rb.length); x++) {
      const a = ra[x] === undefined ? ' ' : ra[x]
      const b = rb[x] === undefined ? ' ' : rb[x]
      const n = noise(x, y + seed)
      line += n < mix ? b : a
    }
    lines.push(line)
  }
  return lines.join('\n')
}

/** True when the user asked the OS to keep the page calm. */
export const prefersReducedMotion = () =>
  typeof window !== 'undefined' &&
  window.matchMedia &&
  window.matchMedia('(prefers-reduced-motion: reduce)').matches

/** Content width of a container in px: clientWidth minus padding/borders,
 * because ASCII grids must fit inside the pre's content box. */
export const innerClientWidth = el => {
  if (!el) return 0
  const cs = getComputedStyle(el)
  const pad =
    parseFloat(cs.paddingLeft) + parseFloat(cs.paddingRight) +
    parseFloat(cs.borderLeftWidth) + parseFloat(cs.borderRightWidth)
  return Math.max(0, el.clientWidth - pad)
}

/**
 * Pick a font-size so a `cols × rows` pre fits both dimensions of its
 * container. Measures the true advance ratio once at a reference size.
 */
export const fitFontPx = (container, cols, rows, { min = 7, max = 26, lineHeight = 1.2 } = {}) => {
  const measure = document.createElement('span')
  measure.style.cssText =
    'position:absolute;visibility:hidden;white-space:pre;' +
    'font-family:JetBrains Mono,monospace;font-size:100px'
  measure.textContent = 'M'.repeat(20)
  document.body.appendChild(measure)
  const adv100 = measure.getBoundingClientRect().width / 20 / 100 // em advance
  measure.remove()
  const avail = innerClientWidth(container)
  const pxW = avail / (cols * adv100)
  const pxH = container.clientHeight / (rows * lineHeight) * 0.96
  return clamp(Math.min(pxW, pxH), min, max)
}
