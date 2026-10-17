// Screenshot helper: desktop + mobile viewport shots of a running site.
import { chromium } from 'playwright-core'

const base = process.argv[2] || 'http://localhost:5210/'
const b = await chromium.launch({ channel: 'chrome', headless: true })
for (const [name, w, h, path] of [
  ['desktop-home', 1440, 900, '/'],
  ['mobile-home', 390, 844, '/'],
]) {
  const p = await b.newPage({ viewport: { width: w, height: h } })
  await p.goto(base + path.slice(1), { waitUntil: 'networkidle' })
  await p.waitForTimeout(2500)
  await p.screenshot({ path: `/tmp/tb-${name}.png` })
  console.log('shot', name)
  await p.close()
}
await b.close()
