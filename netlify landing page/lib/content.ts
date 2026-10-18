// All page copy that is list-shaped lives here. Every line traces to the TaskBridge README
// (see CONTENT.md). Demo content is illustrative and labelled as such on the page.

export const INSTALL_ONE_LINER =
  "curl -fsSL https://taskbridge-landing.pages.dev/install | bash";

export interface Feature {
  glyph: string;
  title: string;
  body: string;
  tools?: string[];
}

export const FEATURES: Feature[] = [
  {
    glyph: "#",
    title: "16 MCP tools for Claude",
    body: "Submit, batch up to 20, wait, tail logs, answer, annotate, cancel, pick models. No polling loops, full observability.",
    tools: ["submit_task", "submit_batch", "wait_for", "get_task_result"],
  },
  {
    glyph: "&",
    title: "Headless auto-worker",
    body: "launchd polls every 60 s, claims oldest-first by priority, streams output to task_logs/<id>.log, and returns a structured result plus a git-aware diff.",
    tools: ["worker.py"],
  },
  {
    glyph: "?",
    title: "Two-way questions",
    body: "The worker can pause with a question block. The task goes waiting, a macOS banner fires, Claude answers, and the run resumes with the answer in context.",
    tools: ["answer_task"],
  },
  {
    glyph: "|",
    title: "Worktree isolation",
    body: "A per-task branch and git worktree, auto-committed on success, cleaned up unless you ask to keep it.",
    tools: ["worktree_keep"],
  },
  {
    glyph: "!",
    title: "Honest permissions",
    body: "readonly reverts writes and reports the reverted files. no-network and no-shell are prompt-level, and labelled that way.",
    tools: ["permission"],
  },
  {
    glyph: "<",
    title: "Reverse bridge",
    body: "Six tools for OpenCode to drive Claude, sync or in the background. Uses the Anthropic API when ANTHROPIC_API_KEY is set, otherwise claude -p.",
    tools: ["claude_ask", "claude_submit", "claude_poll"],
  },
  {
    glyph: "/",
    title: "Public-URL mode",
    body: "One command exposes MCP through ngrok or a Cloudflare quick tunnel, with MCP_ALLOWED_HOSTS paired automatically.",
    tools: ["install.sh", "start_public.sh"],
  },
  {
    glyph: "%",
    title: "Live dispatch board",
    body: "Served at GET / on the same host: tally counts, per-task live logs, reverse jobs, engine tail, and a scrolling feed of fresh output.",
    tools: ["GET /", "/api/*"],
  },
  {
    glyph: "@",
    title: "Caller detection",
    body: "Submissions are stamped with the true caller from the MCP handshake clientInfo, so Claude and ChatGPT dockets stay separate.",
    tools: ["origin"],
  },
  {
    glyph: "*",
    title: "Production reliability",
    body: "Per-attempt timeouts, a 15-minute stale-running reaper with a pid-reuse guard, a single-instance flock, a heartbeat file, and banners you can silence.",
    tools: ["worker_heartbeat", "WORKER_NOTIFY=0"],
  },
];

export interface FaqItem {
  q: string;
  a: string;
}

export const FAQ: FaqItem[] = [
  {
    q: "I get a 421 behind the tunnel.",
    a: "MCP_ALLOWED_HOSTS must exactly match the tunnel host. Run ./install.sh or ./start_public.sh — both set it for you.",
  },
  {
    q: "My tunnel URL changed.",
    a: "Cloudflare quick-tunnel hostnames rotate on every restart. Rerun ./install.sh (or ./start_public.sh), or reserve a fixed ngrok domain in .ngrok-domain.",
  },
  {
    q: "The worker looks stuck.",
    a: "Check ./.venv/bin/python tasks_cli.py heartbeat and task_logs/<id>.log. Stale running tasks are reaped after 15 minutes, and a task's own timeout_sec plus slack is honoured.",
  },
  {
    q: "A task ran twice after I killed the worker.",
    a: "Every attempt runs opencode with a per-attempt argv marker (br-<id>-a<n>) visible in ps. The reaper kills the orphaned CLI child plus its ppid tree, hard-capped so a matching bug can't mass-kill, and a per-pass sweep catches tagged strays. macOS gives no session or env signal, so the ppid walk and argv marker are the whole toolkit — grandchildren reparented to 1 or setsid'd are the known residual. Never pass --session to the CLI: free-tier models refuse to run with it.",
  },
  {
    q: "I don't see any banners.",
    a: "Banners are macOS only. WORKER_NOTIFY=0 silences them on purpose. Full output is always in tasks.db and worker.log.",
  },
  {
    q: "The reverse bridge fails in about a second.",
    a: "Run claude login once, or set ANTHROPIC_API_KEY.",
  },
  {
    q: "opencode is not found.",
    a: "Put it on your PATH, or set OPENCODE_BIN=/path/to/opencode.",
  },
];

export const LIMITATIONS: { title: string; body: string }[] = [
  {
    title: "No token counts",
    body: "The opencode CLI doesn't expose them. usage reports model, latency, attempts, and sandbox status — not tokens.",
  },
  {
    title: "Restrictions are prompt-level",
    body: "no-network and no-shell are instructions to the agent, not OS-enforced sandboxes. worker.py documents this.",
  },
  {
    title: "macOS-first scheduling",
    body: "launchd scheduling and desktop banners are macOS-specific. On Linux, bring your own scheduler (systemd or cron); worker.py still runs by hand.",
  },
  {
    title: "Pickup is not instant",
    body: "Tasks can run up to 1800 s, but the 60 s launchd cadence means pickup latency averages around 30 s.",
  },
];

export const PROJECT_FILES: [string, string][] = [
  ["opencode_bridge_mcp.py", "MCP server (Claude -> queue)"],
  ["task_store.py", "SQLite queue logic"],
  ["tasks_cli.py", "Manual worker CLI"],
  ["worker.py", "Auto-worker (launchd, 60s)"],
  ["claude_control_mcp.py", "Reverse bridge (OpenCode -> Claude)"],
  ["install.sh", "Deps, token, tunnel, serve"],
  ["start_public.sh", "Public tunnel + server (background)"],
  ["requirements.txt", "mcp>=1.0,<2"],
];

export type TermTone = "cmd" | "out" | "faint" | "wait" | "seal" | "signal" | "ember";

export interface TermLine {
  text: string;
  tone: TermTone;
  /** Typed character by character (commands) vs. printed whole (output). */
  typed?: boolean;
}

/** An illustrative session, shaped like README "Usage". Ids, paths and counts are examples. */
export const TERMINAL_SCRIPT: TermLine[] = [
  { text: 'submit_task(title="Add retry tests",', tone: "cmd", typed: true },
  { text: '  instructions="Cover task_store retries; run pytest",', tone: "cmd", typed: true },
  { text: '  working_dir="~/code/target-repo")', tone: "cmd", typed: true },
  { text: '<- { id: "t_0142", status: "pending" }', tone: "faint" },
  { text: 'wait_for(task_ids=["t_0142"], timeout_sec=120)', tone: "cmd", typed: true },
  { text: "* claimed | branch + worktree created", tone: "faint" },
  { text: "* opencode run | streaming task_logs/t_0142.log", tone: "faint" },
  { text: "! waiting -- the worker has a question", tone: "wait" },
  { text: "  ┌ question ─────────────────────────────┐", tone: "wait" },
  { text: "  │ Retries: keep the fixed delay, or     │", tone: "wait" },
  { text: "  │ switch to exponential backoff?        │", tone: "wait" },
  { text: "  └───────────────────────────────────────┘", tone: "wait" },
  { text: 'answer_task(task_id="t_0142", answer="Keep the fixed delay.")', tone: "cmd", typed: true },
  { text: "* resumed with the answer in context", tone: "faint" },
  { text: "+ done", tone: "seal" },
  { text: 'get_task_result(task_id="t_0142")', tone: "cmd", typed: true },
  { text: "{ summary:        \"Added retry tests for task_store\",", tone: "seal" },
  { text: "  files_touched:  [\"tests/test_retries.py\"],", tone: "seal" },
  { text: "  tests_run:      [\"pytest tests/test_retries.py\"],", tone: "seal" },
  { text: "  open_questions: [] }", tone: "seal" },
  { text: "diff   tests/test_retries.py   +48 -0", tone: "signal" },
  { text: "usage  model | latency | attempts 1 | sandbox", tone: "faint" },
];

export const BOARD_FEED: { id: string; text: string; tone: TermTone }[] = [
  { id: "t_0139", text: "pytest -q | 14 passed", tone: "seal" },
  { id: "t_0142", text: "waiting | question posted", tone: "wait" },
  { id: "t_0140", text: "edit src/task_store.py", tone: "faint" },
  { id: "t_0141", text: "claimed | priority 2", tone: "signal" },
  { id: "t_0138", text: "done | diff +12 -3", tone: "seal" },
  { id: "t_0143", text: "pending | depends_on t_0141", tone: "faint" },
  { id: "t_0140", text: "shell | git status --short", tone: "faint" },
  { id: "t_0137", text: "done | auto-committed", tone: "seal" },
];
