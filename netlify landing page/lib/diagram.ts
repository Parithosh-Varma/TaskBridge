// The architecture, as README "How it works" draws it: Claude → bridge → SQLite → worker
// → opencode run in a worktree → structured result → Claude, plus the reverse bridge.
// Mermaid renders DIAGRAM_SOURCE (components/diagram/MermaidGraph.tsx); the arrays below
// own the scroll reveal — order inside a stage is the order the parts draw in.

export type DiagramTone = "paper" | "faint" | "line" | "ember" | "signal" | "seal" | "wait";

export interface DiagramPart {
  /** Mermaid node id, or the edge id declared as `e1@-- … -->`. */
  id: string;
  kind: "node" | "edge";
  stage: number;
  tone: DiagramTone;
}

/** README "How it works", verbatim edges. Edge ids let the reveal find each path. */
export const DIAGRAM_SOURCE = `flowchart LR
  Claude e1@-- "MCP stdio / HTTP" --> Bridge["opencode_bridge_mcp.py"]
  Bridge e2@-- "read / write" --> DB[("tasks.db<br/>SQLite")]
  CLI["tasks_cli.py"] e3@-- "claim / complete" --> DB
  Worker["worker.py<br/>launchd · 60 s"] e4@-- "polls 60 s · oldest-first" --> DB
  Worker e5@-- "opencode run" --> Target["working_dir / worktree"]
  Worker e6@-- "streams logs" --> Logs["task_logs/ID.log"]
  Worker e7@-- "result / structured / usage" --> DB
  Claude e8@-- "get_task_result / wait_for" --> Bridge
  OpenCode e9@-- "claude_ask + 5 more tools" --> Reverse["claude_control_mcp.py"]
  Reverse e10@--> ClaudeCLI["claude -p<br/>Anthropic API"]`;

/** The same graph as text: SSR and no-JS fallback until mermaid takes over. */
export const DIAGRAM_FALLBACK = `Claude --MCP stdio / HTTP--> opencode_bridge_mcp.py
opencode_bridge_mcp.py --read / write--> tasks.db (SQLite)
tasks_cli.py --claim / complete--> tasks.db
worker.py · launchd 60 s --polls 60 s · oldest-first--> tasks.db
worker.py --opencode run--> working_dir / worktree
worker.py --streams logs--> task_logs/ID.log
worker.py --result / structured / usage--> tasks.db
Claude --get_task_result / wait_for--> opencode_bridge_mcp.py
OpenCode --claude_ask + 5 more tools--> claude_control_mcp.py
claude_control_mcp.py --> claude -p / Anthropic API`;

export const DIAGRAM_PARTS: DiagramPart[] = [
  // 01 Submit
  { id: "Claude", kind: "node", stage: 0, tone: "ember" },
  { id: "e1", kind: "edge", stage: 0, tone: "line" },
  { id: "Bridge", kind: "node", stage: 0, tone: "paper" },
  // 02 Queue
  { id: "e2", kind: "edge", stage: 1, tone: "line" },
  { id: "DB", kind: "node", stage: 1, tone: "signal" },
  // 03 Claim
  { id: "CLI", kind: "node", stage: 2, tone: "paper" },
  { id: "e3", kind: "edge", stage: 2, tone: "line" },
  { id: "Worker", kind: "node", stage: 2, tone: "paper" },
  { id: "e4", kind: "edge", stage: 2, tone: "line" },
  // 04 Execute
  { id: "e5", kind: "edge", stage: 3, tone: "seal" },
  { id: "Target", kind: "node", stage: 3, tone: "seal" },
  // 05 Receipt
  { id: "e6", kind: "edge", stage: 4, tone: "line" },
  { id: "Logs", kind: "node", stage: 4, tone: "faint" },
  { id: "e7", kind: "edge", stage: 4, tone: "line" },
  // 06 Read
  { id: "e8", kind: "edge", stage: 5, tone: "ember" },
  // 07 Reverse
  { id: "OpenCode", kind: "node", stage: 6, tone: "seal" },
  { id: "e9", kind: "edge", stage: 6, tone: "wait" },
  { id: "Reverse", kind: "node", stage: 6, tone: "wait" },
  { id: "e10", kind: "edge", stage: 6, tone: "wait" },
  { id: "ClaudeCLI", kind: "node", stage: 6, tone: "ember" },
];

export const DIAGRAM_STAGES = [
  {
    title: "Submit",
    caption: "Claude calls submit_task over MCP -- stdio from Claude Desktop, or HTTP from any MCP client.",
  },
  {
    title: "Queue",
    caption: "durable queue survives restarts -- retries, priorities, dependencies, two-way questions",
  },
  {
    title: "Claim",
    caption: "launchd polls every 60 s; the worker claims oldest-first by priority.",
  },
  {
    title: "Execute",
    caption: "opencode run on a per-task branch in its own git worktree -- auto-committed on success.",
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
    caption: "and back the other way -- OpenCode drives Claude through claude_ask and five more tools.",
  },
] as const;
