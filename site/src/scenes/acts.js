// The five acts of a task's life — parametric ASCII scenes, one per act.
// Each scene is `scene(p) -> {lines}`, p ∈ [0,1] driven by scroll position
// inside the act, so the art rehearses itself as the reader moves.

import { makeGrid, put, putLines, rule, box, lerp, clamp, toString as toText } from '../lib/ascii.js'

export const ACT_W = 68
export const ACT_H = 20

// ─── Act 1 · SUBMIT ───────────────────────────────────────────────────────
const SUBMIT_LINES = [
  'ask.submit_task(',
  '  title        = "add retry tests",',
  '  instructions = "cover claim/complete,',
  '                 tests + acceptance",',
  '  working_dir  = "~/TaskBridge",',
  '  permission   = "readonly", t=600',
  '  priority     = 2',
  ')',
]

const submitResult = p => {
  const g = makeGrid(ACT_W, ACT_H)
  box(g, 0, 1, 43, 13)
  put(g, 13, 1, ' claude · planner ')
  // typewriter reveal, line by line; completes by p ≈ 0.92
  const head = clamp((p / 0.92) * (SUBMIT_LINES.length + 6), 0, SUBMIT_LINES.length + 6)
  SUBMIT_LINES.forEach((line, i) => {
    const chars = clamp((head - i) * 5, 0, line.length)
    if (chars > 0) put(g, 2, 3 + i, line.slice(0, Math.floor(chars)))
  })

  // drain arrow to the queue
  if (p > 0.55) {
    put(g, 21, 14, '│')
    put(g, 21, 15, '▼')
    put(g, 23, 15, 'MCP · 16 tools · no polling loops')
  }
  if (p > 0.72) {
    put(g, 15, 17, '[ tasks.db ]  accepted →  t-8a31c0 · pending')
  }

  // right column: what else rides along
  if (p > 0.30) {
    box(g, 46, 6, 67, 14)
    put(g, 48, 6, ' rides along ')
    putLines(g, 48, 8, [
      'batch      ≤ 20',
      'priority   0..N',
      'depends_on ["…"]',
      'retries    ≤ 5',
      'tags·idem_key',
    ])
  }
  return toText(g)
}

// ─── Act 2 · QUEUE ────────────────────────────────────────────────────────
const QUEUE_ROWS = [
  ['8a31c04be7f2', 'pending   ', ' 2', 'add retry tests'],
  ['5f9d2e11aa04', 'pending   ', ' 2', 'batch gate: wire state'],
  ['3c77b0a412e9', 'pending   ', ' 1', 'fix 421 behind tunnel'],
  ['e0b2f7ca310d', 'waiting   ', ' 1', 'migrate auth to bearer'],
  ['b41f6d09c8a2', 'pending   ', ' 0', 'clean worker logs'],
]
const queueResult = p => {
  const g = makeGrid(ACT_W, ACT_H)
  put(g, 0, 0, 'tasks.db — written once, carried forward')
  rule(g, 0, 66, 1, '─')
  put(g, 0, 2, 'id            status      pri  run')
  const shown = Math.floor(lerp(1, QUEUE_ROWS.length + 0.999, p * 1.15))
  QUEUE_ROWS.slice(0, clamp(shown, 0, QUEUE_ROWS.length)).forEach((r, i) => {
    const y = 4 + i * 2
    put(g, 0, y, r[0])
    put(g, 15, y, r[1])
    put(g, 27, y, r[2])
    put(g, 32, y, r[3])
    rule(g, 0, 66, y + 1, '·')
  })

  // footer facts typed by the end
  if (p > 0.86) {
    put(g, 0, 16, 'oldest-first · by priority · retries & deps enforced')
    put(g, 0, 17, 'survives restarts — the hand-off is the point')
  }
  if (p < 0.14) {
    put(g, 0, 4, '…empty sheet. submit_task writes the first row.')
  }
  return toText(g)
}

// ─── Act 3 · EXECUTE ──────────────────────────────────────────────────────
const LOG_LINES = [
  '▸ claim     t-8a31c04be7f2  (oldest, pri 2)',
  '▸ worktree  .worktrees/br-8a31c04be7f2 ✓',
  '▸ run       opencode run --auto --standalone',
  '· sandbox   prompt: readonly requested',
  '· files     tests/store.test.py (+124)',
  '· tests     12/12 ok · 8.4 min · attempt 1',
]

const executeResult = p => {
  const g = makeGrid(ACT_W, ACT_H)
  box(g, 0, 0, 67, 9)
  put(g, 2, 0, ' worker.py — launchd, 60s cadence ')

  const shown = Math.floor(lerp(0.8, LOG_LINES.length + 0.95, p * 1.2))
  LOG_LINES.slice(0, clamp(shown, 0, LOG_LINES.length)).forEach((l, i) => {
    put(g, 2, 2 + i, l)
  })

  // progress rail across the bottom
  const steps = ['claim', 'run', 'verify', 'commit']
  const stepAt = clamp(Math.floor(p * steps.length), 0, steps.length - 1)
  let rail = ''
  steps.forEach((s, i) => {
    rail += (i === stepAt ? ' ◈ ' : i < stepAt ? ' ▣ ' : ' · ') + s
  })
  put(g, 1, 12, rail.padEnd(63, ' '))
  rule(g, 0, 66, 11, '·')

  if (p > 0.92) {
    put(g, 1, 15, 'reaper guards stale runs — 15 min, pid-reuse proof')
  }
  return toText(g)
}

// ─── Act 4 · RETURN ───────────────────────────────────────────────────────
const returnResult = p => {
  const g = makeGrid(ACT_W, ACT_H)
  box(g, 0, 0, 41, 13)
  put(g, 2, 0, ' get_task_result(t-8a31c0…) ')
  if (p > 0.08) {
    putLines(g, 2, 2, [
      'structured = {',
      '  summary    "retry tests added",',
      '  files      tests/store.test.py',
      '  tests_run  "12/12 ok"',
      '  open_q     []',
      '}',
    ].slice(0, Math.floor(clamp((p - 0.08) / 0.55, 0, 1) * 6)))
  }
  if (p > 0.62) {
    put(g, 2, 10, 'usage     model · latency · attempts')
    put(g, 2, 11, 'diff      git-aware, attached')
  }

  if (p > 0.30) {
    box(g, 44, 0, 67, 13)
    put(g, 46, 0, ' wait_for() ')
    putLines(g, 46, 2, [
      'blocks — no',
      'polling loop —',
      'and returns',
      'claude reads',
      'the diff and',
      'plans step 2.',
    ])
    put(g, 46, 10, 'readonly? writes')
    put(g, 46, 11, 'reverted + labeled')
  }

  if (p > 0.78) {
    put(g, 0, 15, '── success: auto-commit on the branch')
    put(g, 0, 16, '── worktree cleaned unless worktree_keep')
  }
  return toText(g)
}

// ─── Act 5 · ASK BACK ─────────────────────────────────────────────────────
const askResult = p => {
  const g = makeGrid(ACT_W, ACT_H)
  if (p > 0.04) {
    put(g, 0, 1, 't-5f9d2e11aa04  · status → WAITING ❓')
    rule(g, 0, 66, 2, '─')
  }
  if (p > 0.22) putLines(g, 2, 4, ['worker ▸ "token rotate before clear_finished — now or defer?"'])
  if (p > 0.34) put(g, 4, 6, '(macOS banner · WORKER_NOTIFY=1)')
  if (p > 0.50) putLines(g, 2, 8, ['claude ▸ answer_task("rotate first, then clear")'])
  if (p > 0.64) put(g, 4, 10, '▶ resumed — answer rides in the run context')

  if (p > 0.80) {
    rule(g, 0, 66, 13, '─')
    put(g, 0, 15, 'and the bridge runs both ways —')
    putLines(g, 2, 17, [
      'opencode ▸ claude_ask / claude_submit (reverse bridge)',
      '          6 tools · one planner on other end',
    ])
  }
  return toText(g)
}

export const ACT_SCENES = [submitResult, queueResult, executeResult, returnResult, askResult]
