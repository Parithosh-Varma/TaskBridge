// Hero panel — the bridge glyph ⇄ with task traffic flowing along the deck.
// Parametric in `phase` so it can idle-animate (respecting reduced motion).
import { makeGrid, put, rule, box, lerp, toString as toText } from '../lib/ascii.js'

export const HERO_W = 78
export const HERO_H = 14
const ADV_EM = 0.6
const LINE = 1.2

/** Compose the hero panel at a given animation phase (0..1, loops). */
export const buildHero = phase => {
  const g = makeGrid(HERO_W, HERO_H)
  const railTop = 8
  const railMid = 9
  const railBot = 10

  // Two docks, one job each
  box(g, 1, 3, 21, 6)
  put(g, 7, 3, ' claude ')
  put(g, 3, 4, 'plans · delegates')
  put(g, 3, 5, 'asks · waits')

  box(g, 56, 3, 76, 6)
  put(g, 61, 3, ' opencode ')
  put(g, 57, 4, 'edits · tests')
  put(g, 57, 5, 'runs · isolated')

  // The deck: twin rails with task beads flowing left → right
  rule(g, 21, 56, railTop, '═')
  rule(g, 21, 56, railBot, '═')
  const lerpBead = t => 22 + t * 33
  for (let k = 0; k < 7; k++) {
    const t = (phase * 0.9 + k * 0.143) % 1
    const x = Math.floor(lerpBead(t))
    if (x > 21 && x < 56) put(g, x, railMid, t > 0.5 ? '•' : '∘')
  }
  put(g, 37, railMid, '⇄')

  // Under-rail truth line
  put(g, 2, 12, 'submit_task ─▶ tasks.db ─▶ claim ─▶ opencode run --auto ─▶ diff ─▶ wait_for')
  put(g, 2, 13, 'sqlite · survives restarts · worktree isolation · 16 MCP tools')

  return toText(g)
}

/** Frames for the hero loop. */
export const HERO_FRAMES = 120
