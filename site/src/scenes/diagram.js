// ASCII system diagram, tuned by eye (scripts/preview.mjs prints it).
export const WIRE = String.raw`┌─────────────────────────────┐                    ┌─────────────────────────────┐
│         claude side         │                    │        opencode side        │
│  claude desktop · stdio     │                    │  reverse bridge · 6 tools   │
│  any mcp client · http      │                    │  tasks_cli.py · manual      │
│  16 tools on the bridge     │                    │  claims · runs · asks       │
└─────────────┬───────────────┘                    └────────────▲──────────────┘
              │  mcp · stdio / streamable-http                 │
              │  bearer token when public                      │
              ▼                                                │
┌─────────────────────────────┐   claim — oldest first, 60s    │
│  tasks.db · sqlite          │                                │
│  one file · plain rows      │────────────────────────────────┤
│  id · title · instructions  │                                ▼
│  status · priority · deps   │      ┌───────────────────────────────────┐
│  retries · tags · idem_key  │      │             worker.py             │
└─────────────────────────────┘      │  launchd · 60s cadence            │
                                     │  git worktree per task            │
                                     │  opencode run --auto              │
                                     └───────────────┬───────────────────┘
                                                     │ results land back:
                                                     ▼
               {summary, files_touched, tests_run, open_questions}
                        + usage · git-aware diff · live logs
`
