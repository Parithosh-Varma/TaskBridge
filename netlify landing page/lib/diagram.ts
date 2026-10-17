import type { SceneStroke, SceneTone } from "@/components/ascii/AsciiScene";

// The architecture, as README "How it works" draws it: Claude → bridge → SQLite → worker
// → opencode run in a worktree → structured result → Claude, plus the reverse bridge.

const strokes: SceneStroke[] = [];
const put = (row: number, col: number, text: string, tone: SceneTone, stage: number) =>
  strokes.push({ row, col, text, tone, stage });
/** Place `text` so that its middle character sits on `center`. */
const mid = (row: number, center: number, text: string, tone: SceneTone, stage: number) =>
  put(row, center - Math.floor([...text].length / 2), text, tone, stage);

const SPINE = 38;

// 0 — Claude submits over MCP
put(0, 0, "Claude", "ember", 0);
put(0, 7, "──MCP──▶", "line", 0);
// 1 — the bridge writes the durable queue
put(0, 16, "[opencode_bridge_mcp.py]", "paper", 1);
put(0, 41, "──write──▶", "line", 1);
put(0, 52, "⛁", "signal", 1);
put(0, 54, "tasks.db", "signal", 1);
// 2 — the worker claims
put(1, 54, "▲", "line", 2);
put(1, 61, "│", "line", 2);
put(2, 25, "[tasks_cli.py / worker.py]", "paper", 2);
put(2, 52, "──┘", "line", 2);
put(2, 61, "▼", "line", 2);
put(3, SPINE, "│", "line", 2);
put(3, 55, "~60 s · priority", "faint", 2);
put(4, 55, "oldest-first", "faint", 2);
put(4, SPINE, "▼", "line", 2);
// 3 — opencode run, isolated worktree
mid(5, SPINE, "┌── opencode run ── worktree ──┐", "seal", 3);
mid(6, SPINE, "│   edits · shell · tests      │", "paper", 3);
mid(7, SPINE, "└────── structured result ─────┘", "seal", 3);
// 4 — the receipt
put(8, SPINE, "│", "line", 4);
put(9, SPINE, "▼", "line", 4);
mid(10, SPINE, "{ summary, files_touched, tests_run, open_questions } + diff", "seal", 4);
// 5 — Claude reads it back
put(11, SPINE, "│", "line", 5);
put(12, SPINE, "▼", "line", 5);
mid(13, SPINE, "Claude: get_task_result", "ember", 5);
// 6 — and in reverse
put(15, 0, "OpenCode", "seal", 6);
put(15, 9, "╌╌claude_ask╌╌▶", "wait", 6);
put(15, 25, "Claude", "ember", 6);
put(15, 34, "reverse bridge · 6 tools", "faint", 6);

export const DIAGRAM_STROKES = strokes;

export const DIAGRAM_STAGES = [
  {
    title: "Submit",
    caption: "Claude calls submit_task over MCP — stdio from Claude Desktop, or HTTP from any MCP client.",
  },
  {
    title: "Queue",
    caption: "durable queue survives restarts — retries, priorities, dependencies, two-way questions",
  },
  {
    title: "Claim",
    caption: "launchd polls every 60 s; the worker claims oldest-first by priority.",
  },
  {
    title: "Execute",
    caption: "opencode run on a per-task branch in its own git worktree — auto-committed on success.",
  },
  {
    title: "Receipt",
    caption: "a structured result plus a git-aware diff; output streams to task_logs/<id>.log.",
  },
  {
    title: "Read",
    caption: "wait_for blocks instead of polling; get_task_result returns result, structured, usage, diff.",
  },
  {
    title: "Reverse",
    caption: "and back the other way — OpenCode drives Claude through claude_ask and five more tools.",
  },
] as const;
