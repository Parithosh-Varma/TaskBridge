import { useEffect, useRef } from 'react'
import { buildHero, HERO_W, HERO_H, HERO_FRAMES } from '../scenes/hero.js'
import { prefersReducedMotion } from '../lib/ascii.js'

const ADV_EM = 0.6 // JetBrains Mono advance as a fraction of font-size
const LINE = 1.2   // .art line-height

/**
 * Hero panel: the bridge art idles (task beads drift across the rails)
 * and reacts to the pointer — a per-cell flashlight lighting the chars
 * near the cursor. Two stacked <pre> layers, exactly two DOM nodes.
 */
export default function Hero() {
  const wrapRef = useRef(null)
  const baseRef = useRef(null)
  const glowRef = useRef(null)

  useEffect(() => {
    const reduced = prefersReducedMotion()
    let phase = 0.18
    let mouse = null
    let timer = null

    const litText = (text, m) => {
      if (!m) return ''
      return text
        .split('\n')
        .map((line, y) => {
          let row = ''
          for (let x = 0; x < line.length; x++) {
            const d = Math.abs(x - m.cx) / 2.1 + Math.abs(y - m.cy) / 2.6
            row += d < 3.2 && line[x] !== ' ' ? line[x] : ' '
          }
          return row
        })
        .join('\n')
    }

    const paint = () => {
      const base = baseRef.current
      const glow = glowRef.current
      if (!base) return
      const text = buildHero(phase)
      base.textContent = text
      base._text = text
      if (glow) glow.textContent = litText(text, mouse)
    }

    const onMove = e => {
      const base = baseRef.current
      if (!base || !base._text) return
      const size = parseFloat(base.style.fontSize) || 12
      const r = base.getBoundingClientRect()
      mouse = {
        cx: Math.round((e.clientX - r.left) / (size * ADV_EM)),
        cy: Math.round((e.clientY - r.top) / (size * LINE)),
      }
      if (mouse.cx < -3 || mouse.cx > HERO_W + 3 || mouse.cy < -2 || mouse.cy > HERO_H + 2) {
        mouse = null
      }
      paint()
    }

    const onLeave = () => {
      mouse = null
      paint()
    }

    const fit = () => {
      const wrap = wrapRef.current
      const base = baseRef.current
      if (!wrap || !base) return
      const cs = getComputedStyle(wrap)
      const pad =
        parseFloat(cs.paddingLeft) + parseFloat(cs.paddingRight) +
        parseFloat(cs.borderLeftWidth) + parseFloat(cs.borderRightWidth)
      const w = Math.max(180, wrap.clientWidth - pad)
      const sizeW = w / (HERO_W * ADV_EM)
      const sizeH = Math.max(230, Math.min(window.innerHeight * 0.5, 430)) / (HERO_H * LINE)
      const px = Math.max(6, Math.min(sizeW, sizeH, 26))
      base.style.fontSize = px + 'px'
      if (glowRef.current) glowRef.current.style.fontSize = px + 'px'
    }

    if (!reduced) {
      timer = setInterval(() => {
        phase = (phase + 1 / HERO_FRAMES) % 1
        paint()
      }, 90)
    }

    fit()
    paint()
    window.addEventListener('resize', fit)
    const wrap = wrapRef.current
    wrap?.addEventListener('mousemove', onMove)
    wrap?.addEventListener('mouseleave', onLeave)
    return () => {
      if (timer) clearInterval(timer)
      window.removeEventListener('resize', fit)
      wrap?.removeEventListener('mousemove', onMove)
      wrap?.removeEventListener('mouseleave', onLeave)
    }
  }, [])

  return (
    <div className="hero-art" ref={wrapRef} aria-hidden="true">
      <pre className="art hero-base" ref={baseRef} />
      <pre className="art hero-glow" ref={glowRef} />
    </div>
  )
}
