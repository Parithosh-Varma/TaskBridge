// One-shot diagnostic: load a build/dev server in system Chrome, print
// console output, uncaught errors, failed requests, and whether React painted.
import { chromium } from 'playwright-core'

const url = process.argv[2] || 'http://localhost:5200/'

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const page = await browser.newPage()

page.on('console', m => console.log(`[console.${m.type()}]`, m.text().slice(0, 400)))
page.on('pageerror', e => console.log(`[pageerror]`, (e.stack || e.message).slice(0, 800)))
page.on('requestfailed', r =>
  console.log(`[requestfailed]`, r.url(), r.failure()?.errorText || ''),
)
page.on('response', r => {
  if (r.status() >= 400) console.log(`[http ${r.status()}]`, r.url())
})

await page.goto(url, { waitUntil: 'load' })
await page.waitForTimeout(2000)

const info = await page.evaluate(async () => {
  const root = document.querySelector('#root')
  let dynamicImport = 'ok'
  try {
    const src = [...document.querySelectorAll('script[src]')][0]?.src
    if (src) await import(src + '?recheck=' + Math.random())
  } catch (e) {
    dynamicImport = 'THREW: ' + (e.message || String(e))
  }
  return {
    readyState: document.readyState,
    rootHTML: (root || {}).innerHTML?.length || 0,
    rootHasChild: !!root?.firstChild,
    artPres: document.querySelectorAll('pre.art').length,
    scripts: [...document.querySelectorAll('script')].map(s => s.src || '(inline)'),
    bodyChildren: document.body.children.length,
    dynamicImport,
  }
})
console.log(JSON.stringify(info, null, 1))

await browser.close()
