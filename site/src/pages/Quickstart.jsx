import { Link } from 'react-router-dom'
import Code from '../components/Code.jsx'

const INSTALL = [
  'git clone https://github.com/Parithosh-Varma/TaskBridge.git',
  'cd TaskBridge',
  './install.sh',
]

const MANUAL = [
  'python3.12 -m venv .venv',
  './.venv/bin/pip install -r requirements.txt',
  './.venv/bin/python opencode_bridge_mcp.py',
]

const SERVE_HTTP = [
  './.venv/bin/python opencode_bridge_mcp.py \\',
  '     --transport streamable-http --port 8000',
  '# → http://127.0.0.1:8000/mcp',
]

const DESKTOP = [
  '{',
  '  "mcpServers": {',
  '    "taskbridge": {',
  '      "command": "<REPO_PATH>/.venv/bin/python",',
  '      "args": ["<REPO_PATH>/opencode_bridge_mcp.py"],',
  '      "env": {',
  '        "TASK_DB_PATH": "<REPO_PATH>/tasks.db"',
  '      }',
  '    }',
  '  }',
  '}',
]

const VERIFY = [
  'ask claude to list its mcp tools —',
  'you should see submit_task · get_task · list_tasks',
  'under the taskbridge server.',
]

const FROM_CLAUDE = [
  'submit_task(title="Add retry tests",',
  '            instructions="steps… paths… acceptance…",',
  '            working_dir="/path/to/target-repo")',
  'wait_for(task_ids=["<id>"], timeout_sec=120)',
  'get_task_result(task_id="<id>")   → result · structured · usage · diff',
]

const CLI = [
  './.venv/bin/python tasks_cli.py pending',
  './.venv/bin/python tasks_cli.py claim <id>',
  '# … the work happens …',
  './.venv/bin/python tasks_cli.py complete <id> --result "…"',
  './.venv/bin/python tasks_cli.py fail <id> --error "…"   # if it went wrong',
  './.venv/bin/python tasks_cli.py heartbeat              # is the daemon alive',
]

export default function Quickstart() {
  return (
    <>
      <article className="pagehead">
        <p className="eyebrow">clone · install · connect · dispatch</p>
        <h1 className="page-h">quickstart — one command, then talk.</h1>
        <p className="sub">
          Everything below is lifted from the repo's own README — the source of truth for flags and
          paths. Two roads: the installer for the whole public setup, or the manual path for local
          stdio work.
        </p>
      </article>

      <section className="secbox" id="install">
        <h2 className="sec-h"><b>1</b> — run the installer · one command</h2>
        <p className="sub">
          Prompts for your ngrok authtoken (blank = already configured), builds <code>.venv</code>,
          generates or reuses the bearer token in <code>.bridge-token</code>, opens the tunnel,
          pairs <code>MCP_ALLOWED_HOSTS</code>, prints your public connector box, and serves in the
          foreground. <em>Ctrl+C</em> stops serving; the tunnel stays up for next time.
        </p>
        <Code label="public mode — the whole setup" code={INSTALL} accent="rotate the token any time: ./install.sh --rotate" />
      </section>

      <section className="secbox" id="manual">
        <h2 className="sec-h"><b>2</b> — or go manual (local, stdio)</h2>
        <p className="sub">
          For claude desktop on this machine only — no tunnel, no token. venv, install, then run
          the bridge in stdio mode.
        </p>
        <Code label="manual setup" code={MANUAL} accent="python 3.12 · the opencode binary must be on PATH (or set OPENCODE_BIN)" />
      </section>

      <section className="secbox" id="http">
        <h2 className="sec-h"><b>3</b> — or serve http locally</h2>
        <p className="sub">
          Any MCP client (including claude over http) connects to <code>/mcp</code>; the dispatch
          board rides at <code>GET /</code>; health checks live at <code>/health</code>.
        </p>
        <Code label="local http" code={SERVE_HTTP} />
      </section>

      <section className="secbox" id="desktop">
        <h2 className="sec-h"><b>4</b> — wire claude desktop</h2>
        <p className="sub">
          Merge this into{' '}
          <code>~/Library/Application Support/Claude/claude_desktop_config.json</code> under{' '}
          <code>mcpServers</code>, replace <code>&lt;REPO_PATH&gt;</code> with your checkout path,
          and restart claude desktop. (The exact snippet ships as{' '}
          <code>claude_desktop_config.snippet.json</code> in the repo.)
        </p>
        <Code label="claude_desktop_config.snippet.json" code={DESKTOP} accent="stdio transport is local-only — no bearer token needed" />
      </section>

      <section className="secbox" id="publicmode">
        <h2 className="sec-h"><b>5</b> — public mode, briefly</h2>
        <p className="sub">
          <b>ngrok:</b> the installer prompts once and reuses a fixed domain when{' '}
          <code>.ngrok-domain</code> exists. <b>Cloudflare:</b>{' '}
          <code>./start_public.sh</code> runs a background quick tunnel and re-pairs{' '}
          <code>MCP_ALLOWED_HOSTS</code> automatically — rerun it whenever the URL changes.
        </p>
        <Code
          label="the rules of the public door"
          code={[
            '/health        open            (monitoring)',
            'GET /          board — asks for the token (sessionStorage)',
            '/api/*         bearer token required',
            '/mcp           bearer token required',
            '',
            'Authorization: Bearer <your-token>',
          ]}
          accent="tokens live in .bridge-token or BRIDGE_AUTH_TOKEN — never in the repo"
        />
      </section>

      <section className="secbox" id="dispatching">
        <h2 className="sec-h"><b>6</b> — dispatch real work, real fast</h2>
        <p className="sub">
          From claude — file the job, block on it, read the result. No polling loop:
        </p>
        <Code label="claude side" code={FROM_CLAUDE} accent="batch: submit_batch(tasks=[…]) — up to 20, with deps · retries · idem_key per item" />
        <p className="sub">
          Drive it by hand when you want to see every seam (that's the reverse side too):
        </p>
        <Code label="opencode side — tasks_cli.py" code={CLI} accent="launchd every 60s does this loop for you; worker.py's header holds the plist recipe" />
        <p className="sub">
          The reverse bridge mounts in opencode as an MCP server — point it at{' '}
          <code>claude_control_mcp.py</code> and read <code>claude_ask</code> answers synchronously,
          or <code>claude_submit</code> / <code>claude_poll</code> / <code>claude_result</code>{' '}
          for background jobs.
        </p>
      </section>

      <section className="secbox sec-verify" id="verify">
        <h2 className="sec-h">verify the round trip.</h2>
        <Code label="one manoever, zero manual steps" code={VERIFY} />
        <p className="sub sub-foot">
          Then dispatch a task like the <Link to="/">first act of the story</Link> → and watch it
          land on your own board at <code>GET /</code>.
        </p>
      </section>
    </>
  )
}
