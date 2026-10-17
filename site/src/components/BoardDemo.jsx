import { useEffect, useRef, useState } from 'react'
import { BOARD_ROWS, boardAt, BOARD_TICK_MS } from '../scenes/board.js'
import { prefersReducedMotion } from '../lib/ascii.js'

const STATUS = {
  pending: { dot: '◌', n: 'pending' },
  running: { dot: '●', n: 'running' },
  waiting: { dot: '◆', n: 'waiting' },
  completed: { dot: '●', n: 'completed' },
  failed: { dot: '●', n: 'failed' },
  cancelled: { dot: '○', n: 'cancelled' },
}

/**
 * A looping, clearly-labeled simulation of the real dispatch board
 * (which ships at `GET /` on the bridge itself).
 */
export default function BoardDemo() {
  const [tick, setTick] = useState(0)
  const boxRef = useRef(null)
  const onScreen = useRef(false)

  useEffect(() => {
    if (prefersReducedMotion()) {
      setTick(999) // final state, no motion
      return
    }
    const io = new IntersectionObserver(
      entries => entries.forEach(e => (onScreen.current = e.isIntersecting)),
      { threshold: 0.25 },
    )
    io.observe(boxRef.current)
    const timer = setInterval(() => {
      if (onScreen.current && !document.hidden) setTick(t => t + 1)
    }, BOARD_TICK_MS)
    return () => {
      io.disconnect()
      clearInterval(timer)
    }
  }, [])

  const statuses = boardAt(tick)

  return (
    <div className="board" ref={boxRef}>
      <div className="board-head" aria-hidden="true">
        <span>taskbridge · dispatch board</span>
        <span className="board-live">simulated loop</span>
      </div>
      <table className="board-table">
        <thead aria-hidden="true">
          <tr>
            <th>task</th>
            <th style={{ width: '9.5em' }}>status</th>
            <th style={{ width: '13.5em' }}>model</th>
            <th style={{ width: '12em' }}>title</th>
          </tr>
        </thead>
        <tbody>
          {BOARD_ROWS.map((r, i) => {
            const s = STATUS[statuses[i]] || STATUS.pending
            const cls = statuses[i]
            return (
              <tr key={r.id} className={'st-' + cls}>
                <td className="mono-id">{r.id}</td>
                <td>
                  <span className="st-dot" aria-hidden="true">{s.dot}</span> {s.n}
                </td>
                <td className="mono-dim">{r.model}</td>
                <td className="mono-cut" title={r.title}>{r.title}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
      <p className="board-foot">
        sqlite rows, oldest-first by priority · the real board is served at <code>GET /</code> on
        your own bridge — this one just shows the choreography.
      </p>
    </div>
  )
}
