// Simulated dispatch board — an honest loop through statuses the queue
// really uses. Not live data: the real board ships at GET / on the bridge.

export const BOARD_ROWS = [
  { id: '8a31c04be7f2', title: 'add retry tests', model: 'oc/cat-jam-free' },
  { id: '5f9d2e11aa04', title: 'batch gate: wire state', model: 'oc/kimi-k2' },
  { id: '3c77b0a412e9', title: 'fix 421 behind tunnel', model: 'oc/cat-jam-free' },
  { id: 'e0b2f7ca310d', title: 'migrate auth to bearer', model: 'oc/claude-gpt-oss' },
  { id: 'b41f6d09c8a2', title: 'clean worker logs', model: 'oc/cat-jam-free' },
]

// base state + per-beat transitions; loop ends with a quiet hold
export const BOARD_START = ['pending', 'pending', 'failed', 'waiting', 'completed']

export const BOARD_BEATS = [
  { i: 0, s: 'running' },
  { i: 1, s: 'running' },
  { i: 0, s: 'completed' },
  { i: 2, s: 'running' },
  { i: 1, s: 'completed' },
  { i: 4, s: 'pending' },
  { i: 2, s: 'completed' },
  { i: 4, s: 'running' },
  { i: 3, s: 'running' },
  { i: 3, s: 'completed' },
  { i: 4, s: 'completed' },
  { i: 1, s: 'pending' },
]

/** Tick the board to `t`. */
export const boardAt = t => {
  const now = t % (BOARD_BEATS.length + 8) // beats, hold eight ticks, loop
  const statuses = [...BOARD_START]
  const applied = Math.min(now, BOARD_BEATS.length)
  for (let k = 0; k < applied; k++) {
    const b = BOARD_BEATS[k]
    statuses[b.i] = b.s
  }
  return statuses
}

export const BOARD_TICK_MS = 850
