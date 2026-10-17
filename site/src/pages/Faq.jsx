import { Link } from 'react-router-dom'

const QA = [
  {
    q: '421 behind a tunnel?',
    a: [
      'The http bridge only answers hosts listed in MCP_ALLOWED_HOSTS — a mismatch is a deliberate 421 so a hijacked mirror fails loudly instead of quietly proxying your queue.',
      'Rerun ./install.sh or ./start_public.sh: both re-pair the allowlist with the live tunnel host. When using a cloudflare quick tunnel, the URL rotates — re-pairing is expected after each rerun.',
    ],
  },
  {
    q: 'auth keeps failing — 401 on /mcp or /api/*?',
    a: [
      'The public door wants: Authorization: Bearer <token>. The token is the one in .bridge-token (or BRIDGE_AUTH_TOKEN if you set it). /health is the only path without it.',
      'Rotated the token? Every client must re-pair — the board (GET /) asks for the new token once and keeps it in sessionStorage.',
    ],
  },
  {
    q: 'a task is stuck in running — what really happens?',
    a: [
      'Every attempt is tagged br-<id>-a<n> and visible in ps. If the worker dies mid-run, the 15-minute reaper reaps the orphan — with a pid-reuse proof so it never kills an unrelated process that recycled the pid.',
      'Check worker_heartbeat for the daemon, get_task_logs for the tail while it is still running. Failed attempts are honest: they may retry (retries ≤ 5) with an optional retry_model for a second opinion.',
    ],
  },
  {
    q: 'is no-network / no-shell a real sandbox?',
    a: [
      'Work runs headless inside a fresh git worktree — one branch per task, auto-committed on success — so the working tree stays clean.',
      'Permissions are prompt-hinted, not kernel-enforced: a readonly task that writes anyway has its writes reverted and recorded as reverted (never silently kept). Tighten independently if you need more.',
    ],
  },
  {
    q: 'how does ordering, batching and dedupe work?',
    a: [
      'Rows sit oldest-first by priority; dependencies gate the claim (a task runs only after its upstream row is completed). submit_batch carries up to 20 jobs, each with its own deps · retries · idem_key.',
      'An idempotency key makes refiling safe: the bridge declines a re-submit with the same key while the original is alive.',
    ],
  },
  {
    q: 'which model runs the work?',
    a: [
      'What the binary offers shows up in list_models. Set the queue-wide default with set_default_model, or carry a model field on the task itself. The result reports model and latency honestly.',
      'Token counts stay unknown until the opencode runtime exposes them — the usage block never invents the field.',
    ],
  },
  {
    q: 'where do logs live?',
    a: [
      'task_logs/<id>.log on disk, get_task_logs for a live tail from claude, and the dispatch board at GET / streams the same tail in the browser.',
      'The board also shows per-task status, counts by state, the reverse-job feed — and asks for the token only when you want detail, not for monitoring.',
    ],
  },
  {
    q: 'asks back — how do waiting tasks get answered?',
    a: [
      'A stalled task flips to waiting and fires a macOS banner (set WORKER_NOTIFY=1). claude answers through answer_task and the run resumes with the answer in context.',
      'From the other seat: the reverse bridge mounts claude_ask / claude_submit / claude_poll / claude_result / claude_cancel / claude_status inside opencode.',
    ],
  },
  {
    q: 'what must be on the machine?',
    a: [
      'python 3.12, an opencode binary on PATH (or OPENCODE_BIN pointed at it), and for public mode a free ngrok authtoken or the cloudflared binary. The installer wires all three and prints the connector box.',
      'stdio-only desktop use needs none of the tunnel world — venv + bridge + claude_desktop_config.json.',
    ],
  },
]

export default function Faq() {
  return (
    <>
      <article className="pagehead">
        <p className="eyebrow">the queue's help desk</p>
        <h1 className="page-h">faq — straight answers.</h1>
        <p className="sub">
          The questions this bridge actually produced, with the answers the README and the code give.
          No marketing optimism: if something is prompt-hinted rather than enforced, it says so.
        </p>
      </article>

      <section className="secbox faq-wrap" id="faq-list">
        <div className="faq-list">
          {QA.map(item => (
            <details key={item.q} className="faq">
              <summary className="faq-q">
                <span className="faq-mark" aria-hidden="true">▸</span> {item.q}
              </summary>
              <div className="faq-a">
                {item.a.map((p, i) => (
                  <p key={i}>{p}</p>
                ))}
              </div>
            </details>
          ))}
        </div>
        <p className="sub sub-foot">
          Deeper detail lives in the repo README — and the fastest route to a working bridge is the{' '}
          <Link to="/quickstart">quickstart →</Link>
        </p>
      </section>
    </>
  )
}
