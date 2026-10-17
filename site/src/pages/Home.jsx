import { Link } from 'react-router-dom'
import Hero from '../components/Hero.jsx'
import Acts from '../components/Acts.jsx'
import BoardDemo from '../components/BoardDemo.jsx'
import Code from '../components/Code.jsx'

const INSTALL = [
  'git clone https://github.com/Parithosh-Varma/TaskBridge.git',
  'cd TaskBridge',
  './install.sh        # deps → bearer token → tunnel → serve',
]

const ACTS = [
  {
    num: '01',
    word: 'SUBMIT',
    body: [
      'Claude asks for work in its own language — a title, instructions with acceptance criteria, the repo to do it in. The bridge stamps the request with permissions, priority, and a retry budget, then writes it to SQLite as a pending row.',
      'Durable from the first second: the request survives a crashed daemon, a restart, a next day. Batch up to twenty in one call, chain them with dependencies, or tag them for later.',
    ],
    code: {
      label: 'from claude — over MCP',
      code: [
        'submit_task(',
        '  title        = "add retry tests",',
        '  instructions = "cover claim/complete path…',
        '                  acceptance: 12 cases pass",',
        '  working_dir  = "~/TaskBridge",',
        '  permission   = "readonly",  # or default',
        '  priority     = 2',
        ')',
      ],
      accent: '→ t-8a31c04be7f2 · pending · stamped by the caller',
    },
  },
  {
    num: '02',
    word: 'QUEUE',
    body: [
      'The queue is one SQLite file. Rows sit oldest-first by priority, gated by dependencies, bounded by retry plans, de-duplicated by idempotency keys. You can open it with any sqlite client and watch the work sit there in plain rows.',
      'The hand-off is the point: Claude does not need OpenCode alive, OpenCode does not need Claude online. Time and restarts are absorbed by the file.',
    ],
    accent: 'one file · no server · no external queue to babysit',
  },
  {
    num: '03',
    word: 'EXECUTE',
    body: [
      'A headless worker polls every 60 seconds, claims the oldest claimable row, and runs opencode run --auto inside a fresh git worktree — one branch per task, auto-committed on success, cleaned up after.',
      'Output streams to task_logs/<id>.log. Per-attempt timeouts and a 15-minute stale-run reaper keep the queue honest; permissions stay honest too — readonly work has its writes reverted and labeled as reverted.',
    ],
    accent: 'isolation is default, not opt-in',
  },
  {
    num: '04',
    word: 'RETURN',
    body: [
      'wait_for() blocks and pays off once: a structured summary, the files touched, the tests that ran, open questions — with the git-aware diff and usage attached. Claude reads it and plans the next move.',
      'No polling loops, no mismatched half-results — the structured return is designed for a planner that wants to keep moving.',
    ],
    accent: 'readonly? writes are reverted — then labeled, never hidden',
    code: {
      label: 'what comes back',
      code: [
        '{',
        '  summary    "retry tests added",',
        '  files_touched ["tests/store.test.py"],',
        '  tests_run  "12/12 ok",',
        '  open_questions  [],',
        '  diff       "…+124 lines, git-aware…",',
        '  usage      {model, latency, attempts}',
        '}',
      ],
    },
  },
  {
    num: '05',
    word: 'ASK BACK',
    body: [
      'The longest journey a queue can take is back. When the worker stalls on a real decision, it pauses the task as waiting, fires a macOS banner, and Claude answers through answer_task — the run resumes with the answer in context.',
      'And it goes the whole way: the reverse bridge hands OpenCode six tools to drive Claude itself — synchronous questions, background answers, cancel — all from the executor seat.',
    ],
    accent: 'in both directions, neither side is a dead end',
  },
]

const MANIFEST_CLAUDE = [
  ['submit_task', 'file one job — title, instructions, permission, model, priority'],
  ['submit_batch', 'up to 20 jobs, each with its own deps · retries · idem_key'],
  ['get_task', 'the row as filed: fields, timestamps, caller'],
  ['get_task_result', 'structured summary + usage + the git-aware diff'],
  ['get_task_logs', 'live tail — read the log while it is still running'],
  ['wait_for', 'block until your ids settle; timeout instead of polling'],
  ['answer_task', 'feed the answer to a waiting task, resume the run'],
  ['list_tasks', 'dump the docket with status / limit / tag filters'],
  ['queue_status', 'counts by status, attempts in flight'],
  ['worker_heartbeat', 'is the daemon alive, when did it last claim'],
  ['add_task_note', 'write a note onto a task for the record'],
  ['cancel_task', 'mark a pending task cancelled — never claimed'],
  ['clear_finished', 'sweep completed / failed / cancelled out of the way'],
  ['list_models', 'models the worker can run right now'],
  ['set_default_model', 'choose the queue-wide default'],
  ['ping', 'liveness, one round trip'],
]

const MANIFEST_REVERSE = [
  ['claude_ask', 'one-shot question from OpenCode, synchronous answer'],
  ['claude_submit', 'hand Claude a task, get a job id back'],
  ['claude_poll', 'is the background job still running, tail so far'],
  ['claude_result', 'collect the finished output in full'],
  ['claude_cancel', 'stop a running background job'],
  ['claude_status', 'cli present? key set? login needed?'],
]

const NUMBERS = [
  ['16', 'mcp tools on the bridge, claude side'],
  ['6', 'tools in the reverse bridge, opencode side'],
  ['~30s', 'average pickup — launchd ticks every 60s'],
  ['1,800s', 'longest run a task may take by default'],
  ['20', 'tasks accepted by a single batch submit'],
  ['15min', 'stale-run reaper deadline, pid-reuse proof'],
]

export default function Home() {
  return (
    <>
      {/* ───────────────────────── hero ───────────────────────── */}
      <section className="hero">
        <p className="eyebrow hero-eyebrow">mcp bridge · sqlite queue · headless workers</p>
        <Hero />
        <h1 className="hero-h">
          <span className="hero-h1">Claude plans.</span>
          <span className="hero-h2">OpenCode builds.</span>
        </h1>
        <p className="sub sub-hero">
          TaskBridge hands work from your planner to headless OpenCode agents through a durable
          SQLite queue. Repos stay on your machine; the structured result and diff come back.
        </p>
        <div className="hero-cta">
          <Code code={INSTALL} label="the one command" accent="python 3.12 · an opencode binary on PATH · free ngrok for public mode" />
          <div className="hero-btns">
            <Link className="btn btn-solid" to="/quickstart">quickstart →</Link>
            <Link className="btn btn-ghost" to="/architecture">how it works</Link>
          </div>
        </div>
      </section>

      {/* ───────────────────────── acts ───────────────────────── */}
      <Acts acts={ACTS} />

      {/* ───────────────────────── board ───────────────────────── */}
      <section className="secbox" id="board">
        <p className="eyebrow">the dispatch board</p>
        <h2 className="sec-h">the queue has a dashboard.</h2>
        <p className="sub">
          Served on the same public URL as the MCP endpoint: tallies, per-task live logs, the
          reverse-job feed, an engine tail — and the tokens for nothing else. Here is a loop through
          the states a task really walks:
        </p>
        <BoardDemo />
      </section>

      {/* ───────────────────────── manifest ───────────────────────── */}
      <section className="secbox" id="manifest">
        <p className="eyebrow">the manifest</p>
        <h2 className="sec-h">twenty-two tools, honest list.</h2>
        <p className="sub">No polling loops. No blind spots. This is the whole verb set.</p>
        <div className="manifest-cols">
          <div>
            <h3 className="mini-h">for claude — 16</h3>
            <ul className="manifest">
              {MANIFEST_CLAUDE.map(([n, d]) => (
                <li key={n}>
                  <code className="m-name">{n}</code>
                  <span className="m-desc">{d}</span>
                </li>
              ))}
            </ul>
          </div>
          <div>
            <h3 className="mini-h">for opencode — 6 (reverse)</h3>
            <ul className="manifest">
              {MANIFEST_REVERSE.map(([n, d]) => (
                <li key={n}>
                  <code className="m-name">{n}</code>
                  <span className="m-desc">{d}</span>
                </li>
              ))}
            </ul>
          </div>
        </div>
      </section>

      {/* ───────────────────────── numbers ───────────────────────── */}
      <section className="secbox" id="holds">
        <p className="eyebrow">why it holds</p>
        <h2 className="sec-h">numbers you can hold it to.</h2>
        <div className="numbers">
          {NUMBERS.map(([n, d]) => (
            <div className="num-cell" key={d}>
              <span className="num-n">{n}</span>
              <span className="num-d">{d}</span>
            </div>
          ))}
        </div>
        <p className="sub sub-foot">
          one SQLite file · worktrees per task · macOS daemon (launchd) · bearer token when the
          bridge is public · apache-2.0
        </p>
      </section>

      {/* ───────────────────────── closing ───────────────────────── */}
      <section className="closing">
        <p className="eyebrow">wire the desk</p>
        <h2 className="closing-h">
          put claude to work<span className="amber"> → </span>while you're reading this.
        </h2>
        <p className="sub">The install prints your connector box in one pass. Thirty seconds.</p>
        <div className="closing-btns">
          <Link className="btn btn-solid btn-lg" to="/quickstart">run the quickstart →</Link>
          <a
            className="btn btn-ghost btn-lg"
            href="https://github.com/Parithosh-Varma/TaskBridge"
            target="_blank"
            rel="noreferrer"
          >
            star on github ↗
          </a>
        </div>
      </section>
    </>
  )
}
