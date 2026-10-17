# Content contract — page section → README source

Source: `README.md` of github.com/Parithosh-Varma/TaskBridge. Every claim on the page traces to one of these headings.

1. Nav — title + "Claude plans. OpenCode builds." (README title + tagline blockquote). Stars: live from the GitHub API.
2. Hero — h1 = tagline; sub = tagline blockquote + "structured summary, git-aware diff, logs, and usage" (intro paragraph); install = Quickstart "One command" block.
3. Why — "Why this exists": can't touch your filesystem / lives outside Claude's context / closes the loop; pull-quote from its three bullets.
4. Architecture — "How it works" mermaid flowchart + Features (auto-worker 60 s, oldest-first by priority, structured result shape) + Usage (wait_for, get_task_result) + reverse bridge (claude_ask).
5. Features — the ten "Features" bullets, tool names verbatim (16 tools, submit_batch up to 20, 6 reverse tools, 15-min reaper, flock, heartbeat).
6. Quickstart — "Quickstart" (prereqs, install.sh behaviour, connector box) + "Authentication" (public URL + bearer token) + "Usage" steps 1–3.
7. Demo terminal — "Usage" (submit_task / wait_for / answer_task / get_task_result) + Features "Two-way questions"; content labelled illustrative; usage shows model/latency/attempts/sandbox per Limitations (no tokens).
8. Demo board — Features "Live dispatch board": tally counts, per-task live logs, scrolling feed, served at `GET /`.
9. FAQ — "Troubleshooting / FAQ", all seven entries, double-run entry summarised incl. ppid walk + known residual.
10. Limitations — "Limitations", all four entries (tokens, prompt-level restrictions, macOS-specific, 60 s cadence / 1800 s).
11. Final CTA — "License": Apache-2.0, "Fork it, self-host it, build on it."
12. Footer — "Project structure" file list.
13. Numbers allowed: 16, 20, 6, 60 s, ~30 s average pickup, 1800 s, 15 min, 900 s / +120 s, Python 3.12.
14. Not used: testimonials, logos, metrics, superlatives, emoji. Nothing beyond the README is claimed.
15. Illustrative content (demo task names, ids, diff counts) is labelled as such on the page.
