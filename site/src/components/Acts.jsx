import { useEffect, useRef } from 'react'
import { ACT_SCENES, ACT_W, ACT_H } from '../scenes/acts.js'
import { dissolve, clamp, prefersReducedMotion, fitFontPx } from '../lib/ascii.js'
import Banner from './Banner.jsx'
import Code from './Code.jsx'

/**
 * Scrolly stage: a sticky ASCII viewport on one side, an act per screen of
 * scroll on the other. The art is a single <pre>; every frame rewrites its
 * textContent (cheap — ~1.4k chars) and dissolves between acts per-cell.
 */
export default function Acts({ acts }) {
  const frameRef = useRef(null)
  const artRef = useRef(null)
  const railRef = useRef(null)
  const panelsRef = useRef([])

  useEffect(() => {
    const reduced = prefersReducedMotion()
    let raf = 0
    let lastText = ''

    const fit = () => {
      if (!frameRef.current || !artRef.current) return
      const px = fitFontPx(frameRef.current, ACT_W, ACT_H, { min: 8, max: 26 })
      artRef.current.style.fontSize = px + 'px'
    }

    const railText = (actIdx, p) => {
      const words = acts.map(a => a.word)
      return acts
        .map((a, i) => {
          const fill = i < actIdx ? 10 : i === actIdx ? Math.round(clamp(p, 0, 1) * 10) : 0
          const bar = '▰'.repeat(fill) + '▱'.repeat(10 - fill)
          return `${a.num}  ${bar}  ${words[i].padEnd(8)}`
        })
        .join('\n')
    }

    const render = () => {
      const panels = panelsRef.current.filter(Boolean)
      if (!panels.length || !artRef.current) return
      const vh = window.innerHeight

      let actIdx = 0
      let bestD = Infinity
      let p = 0
      panels.forEach((el, i) => {
        const r = el.getBoundingClientRect()
        const center = r.top + r.height / 2
        const d = Math.abs(center - vh / 2)
        if (d < bestD) {
          bestD = d
          actIdx = i
          p = clamp(0.5 - (center - vh / 2) / r.height, 0, 1)
        }
      })

      const cur = ACT_SCENES[actIdx](p)
      const mixStart = 0.86
      const nextMix =
        actIdx < panels.length - 1 && p > mixStart ? (p - mixStart) / (1 - mixStart) : 0

      let text
      if (reduced) {
        text = ACT_SCENES[actIdx](p < 0.5 ? 0 : 1)
      } else if (nextMix > 0) {
        text = dissolve(
          cur.split('\n'),
          ACT_SCENES[actIdx + 1](0.06).split('\n'),
          nextMix,
          actIdx * 13,
        )
      } else {
        text = cur
      }

      if (text !== lastText) {
        artRef.current.textContent = text
        lastText = text
      }
      if (railRef.current) {
        const rail = railText(actIdx, p)
        if (rail !== railRef.current.dataset.last) {
          railRef.current.textContent = rail
          railRef.current.dataset.last = rail
        }
      }
    }

    const schedule = () => {
      if (raf) return
      raf = requestAnimationFrame(() => {
        raf = 0
        render()
      })
    }

    const onResize = () => {
      fit()
      schedule()
    }

    fit()
    render()
    window.addEventListener('scroll', schedule, { passive: true })
    window.addEventListener('resize', onResize)
    return () => {
      window.removeEventListener('scroll', schedule)
      window.removeEventListener('resize', onResize)
      cancelAnimationFrame(raf)
    }
    // acts data is static for the page lifetime
  }, [acts])

  return (
    <section className="acts" id="acts">
      <div className="acts-col acts-col-art">
        <div className="acts-stage" ref={frameRef}>
          <pre className="art acts-art" aria-hidden="true" ref={artRef} />
          <div className="acts-rail" ref={railRef} aria-hidden="true" />
          <p className="acts-hint" aria-hidden="true">▼ scroll — the art rehearses each act</p>
        </div>
      </div>

      <div className="acts-col acts-col-copy">
        {acts.map((a, i) => (
          <article
            className="acts-panel"
            key={a.num}
            ref={el => (panelsRef.current[i] = el)}
          >
            <header className="acts-head">
              <p className="eyebrow">
                act <b className="acts-num">{a.num}</b><span className="acts-of">/05</span>
              </p>
              <div className="acts-banner">
                <Banner word={a.word} />
              </div>
            </header>
            {a.body.map((para, j) => (
              <p className="prose" key={j}>{para}</p>
            ))}
            {a.code && <Code {...a.code} />}
            {a.accent && <p className="accent-line">{a.accent}</p>}
          </article>
        ))}
      </div>
    </section>
  )
}
