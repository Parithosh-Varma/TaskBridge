import { Link } from 'react-router-dom'
import Table from '../components/Table.jsx'
import { WIRE } from '../scenes/diagram.js'

const COMPONENTS = [
  ['opencode_bridge_mcp.py', 'claude side', 'the MCP server — stdio for claude desktop, streamable-http / sse over the tunnel, host allowlist'],
  ['task_store.py', 'shared', 'all the sqlite logic: submit, claim, complete, retries, deps, notes, heartbeat'],
  ['worker.py', 'executor', 'headless runner — launchd every 60s, worktrees, timeouts, reaper, banners'],
  ['tasks_cli.py', 'opencode side', 'manual loop commands: pending · show · claim · complete · fail · logs'],
  ['claude_control_mcp.py', 'reverse', 'the other bridge — OpenCode calling Claude (api or claude -p)'],
  ['install.sh', 'bootstraps', 'one command: deps, bearer token, ngrok tunnel, allowlist pairing, serve'],
  ['start_public.sh', 'bootstraps', 'background variant — fixed ngrok domain or cloudflare quick tunnel'],
  ['bridge_dashboard.html', 'watcher', 'the live dispatch board served at GET / on the same host'],
]

const STATUSES = [
  ['pending', 'filed and waiting — ordered by priority, gate by deps'],
  ['running', 'claimed by the worker, worktree live, log streaming'],
  ['waiting', 'stalled on a real question — banner fired for claude'],
  ['completed', 'result + diff attached; branch committed, worktree cleaned'],
  ['failed', 'attempt spent; may retry with retries / retry_model set'],
  ['cancelled', 'never claimed again — swept by clear_finished'],
]

const CONFIG = [
  ['TASK_DB_PATH', 'bridge · cli', 'where the queue lives (default <repo>/tasks.db)'],
  ['WORKER_MODEL', 'worker', 'default model, e.g. opencode/cat-jam-free'],
  ['OPENCODE_BIN', 'worker', 'path to the opencode binary (else PATH)'],
  ['WORKER_NOTIFY', 'worker', '1 = macOS banners on questions, 0 = silence'],
  ['MCP_ALLOWED_HOSTS', 'bridge http', 'exact tunnel host(s); mismatch = 421'],
  ['BRIDGE_AUTH_TOKEN', 'bridge http', 'bearer token (or the .bridge-token file)'],
  ['ANTHROPIC_API_KEY', 'reverse', 'direct api backend; else claude -p'],
]

const GUARANTEES = [
  'the queue is a sqlite file — safe to copy, safe to restart against, one truth for both sides',
  'every attempt is tagged (br-<id>-a<n>) and visible in ps — the reaper kills orphans with a pid-reuse guard, then sweeps strays',
  'dependencies gate claims; a task only runs when its upstream row is completed',
  'readonly runs have their writes reverted and reported as reverted — never silently kept',
  'usage reports model, latency and attempts honestly; token counts stay unknown until opencode exposes them',
]

const LENS = [
  ['claude plans', 'breaks work down, delegates it, reads results — stays the interface'],
  ['opencode builds', 'edits, shells, tests — headless, in a worktree, on your machine'],
  ['sqlite guarantees', 'survives restarts, absorbs retries, keeps the docket honest'],
]

export default function Architecture() {
  return (
    <>
      <article className="pagehead">
        <p className="eyebrow">the wire · the file · the daemon</p>
        <h1 className="page-h">how it works — architecture.</h1>
        <p className="sub">
          Two agents, one sqlite file, one worker. Claude talks MCP over stdio or http; the worker
          claims rows and runs opencode inside git worktrees; results flow back as structured
          payloads. Nothing leaves your machine except the tunnel you choose.
        </p>
      </article>

      <section className="secbox" id="mcp">
        <h2 className="sec-h">the wire.</h2>
        <pre className="art art-diagram" aria-label="ascii diagram: claude and opencode through a sqlite task queue">{WIRE}</pre>
      </section>

      <section className="secbox" id="components">
        <h2 className="sec-h">the parts.</h2>
        <p className="sub">Eight real files carry the whole weight:</p>
        <Table head={['file', 'side', 'what it does']} rows={COMPONENTS} />
      </section>

      <section className="secbox" id="statuses">
        <h2 className="sec-h">the states.</h2>
        <p className="sub">
          A task's life is small and legible — six statuses, no hidden lifetimes:
        </p>
        <Table head={['status', 'meaning']} rows={STATUSES} />
        <p className="accent-line">
          pending → running → completed / failed · waiting cuts in whenever the worker needs an
          answer · cancelled erases the future · retries are bounded (≤5) with an optional
          retry_model for second opinions.
        </p>
      </section>

      <section className="secbox" id="config">
        <h2 className="sec-h">the knobs.</h2>
        <p className="sub">Eight environment variables, all documented, none secret-sauce:</p>
        <Table head={['variable', 'who', 'purpose']} rows={CONFIG} />
      </section>

      <section className="secbox" id="holds">
        <h2 className="sec-h">what keeps it honest.</h2>
        <ul className="guarantees">
          {GUARANTEES.map(g => <li key={g}>{g}</li>)}
        </ul>
      </section>

      <section className="secbox sec-lens" id="lens">
        <div className="lens">
          {LENS.map(([k, v]) => (
            <div className="lens-cell" key={k}>
              <span className="lens-k">{k}</span>
              <span className="lens-v">{v}</span>
            </div>
          ))}
        </div>
        <p className="sub sub-foot">
          depth on every endpoint lives in the README — and the fastest route to a working bridge is
          the <Link to="/quickstart">quickstart →</Link>
        </p>
      </section>
    </>
  )
}
