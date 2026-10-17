# Build TaskBridge's Landing Page — Agentic Build Prompt

Paste this entire file into Claude Code (Opus 5.5) with `~/Downloads/TaskBridge` as the working directory.

---

## ROLE & MODE

You are building a production landing page inside this repository. Work agentically: scaffold the project, write every file, run the dev server, verify visually, iterate until it is genuinely premium. Do not stop at scaffolding and claim completion — the bar is a page that looks finished, runs at 60fps, and passes `next build`.

Do NOT modify any existing files (`README.md`, `worker.py`, `opencode_bridge_mcp.py`, `bridge_dashboard.html`, etc.). All new work goes in a new `landing/` directory.

## WHAT YOU'RE SELLING

**TaskBridge** — "Claude plans. OpenCode builds." Claude submits coding tasks over MCP. An auto-worker picks them up in ~60 s, runs `opencode run` in an isolated git worktree, and returns a structured summary, git-aware diff, logs, and usage for Claude to read. Works from Claude Desktop (stdio), any MCP client over HTTP, and in reverse — OpenCode can drive Claude too.

Read the full `README.md` in this repo before writing any copy. Every claim on the page must trace back to it. No invented features, no fake metrics, no testimonial quotes, no logo walls. This tool's honesty is its brand: limitations are stated openly.

## DELIVERABLE

A new `landing/` directory containing a complete Next.js app:

- **Next.js 15+ App Router, TypeScript, Tailwind CSS v4**
- `lucide-react` for UI icons ONLY (chevrons, copy, external-link, check) — **all decorative/hero art is hand-built ASCII, never icon fonts or SVG "tech art"**
- `motion` (Framer Motion) for section reveals
- No component libraries (shadcn, MUI, Chakra). Everything hand-built.
- Zero external image assets — the ASCII engine is the art. The only raster-ish element allowed is a CSS-generated grain overlay.

Commands to run: scaffold, `npm run dev`, verify in browser (or via screenshots if you have browser tooling), `npm run build` must pass with zero errors. Fix every TypeScript and lint warning.

## VISUAL DIRECTION — "The Dispatch Hall, at night"

Premium, warm, terminal-native. The aesthetic references the repo's own `bridge_dashboard.html`: a night-time rail dispatcher's office rendered as software. Restrained glow, dithered gradients, teletype texture. Nothing neon-crypto, nothing purple-gradient-SaaS.

**Palette (define as CSS custom properties + Tailwind theme tokens):**

| Token | Hex | Use |
|---|---|---|
| `--bg` | `#100c08` | page background, warm near-black |
| `--panel` | `#1a140e` | cards, raised surfaces |
| `--panel-2` | `#221a12` | hover states, nested surfaces |
| `--line` | `#33291d` | 1px borders (always borders, never heavy shadows) |
| `--paper` | `#efe4cc` | primary text, teletype paper |
| `--faint` | `#9c8c72` | secondary text, labels |
| `--ember` | `#e2603a` | gradient head — Claude side |
| `--signal` | `#f2a007` | amber — live/active, primary accent |
| `--seal` | `#8fc39a` | green — completion — OpenCode side |
| `--wait` | `#b9a3e3` | violet — waiting/questions |

Gradients flow **ember → signal → seal** (planning heat → dispatch → execution done). Use this ramp consistently in the ASCII dithering, underlines, and progress elements — but keep large surfaces flat and dark. Glow is earned, not sprayed.

**Typography (next/font, both variable):**
- Display/headings: **JetBrains Mono** — tight tracking, heavy weights, uppercase for eyebrow labels. The machine voice.
- Body: **Inter** — comfortable, quiet, 1.6 line-height.
- Eyebrows/kickers: 11px, uppercase, `letter-spacing: 0.22em`, `--faint` color — exactly like the dashboard's `.eyebrow`.

**Texture:** fine grain overlay via an inline SVG feTurbulence data-URI at ~3% opacity, fixed, pointer-events-none. Subtle vignette on the hero. No colored blobs, no mesh gradients.

## THE ASCII ENGINE (build this first, it powers four sections)

Create `landing/components/ascii/` with a small, well-typed engine:

1. **`useAsciiCanvas`** — fixed-grid canvas renderer. Cell size ~14px desktop / 10px mobile. Monospace glyphs drawn per cell from a precomputed glyph atlas. Brightness sources composited per cell:
   - a low-frequency drift field (`fbm`-style, cheap — 2–3 octaves, evaluated per cell, animated by time)
   - **scroll progress** of the owning section (0→1 across entry-to-exit)
   - **pointer proximity** — mouse position warps and brightens nearby cells (spotlight + slight swirl), lerped for smoothness
   char chosen by brightness dithering (ramp `` ·:-=+*#%@``), color chosen by the ember→signal→seal ramp. Perf: render at 30fps max, `devicePixelRatio` capped at 2, pause rendering entirely via IntersectionObserver when off-screen.

2. **`AsciiScene`** — line-art renderer on the same grid for diagrams: arrays of text lines, per-line reveal progress, so box edges / connectors / labels draw themselves character-by-character as scroll advances.

3. **Reduced motion contract:** if `prefers-reduced-motion`, render a single static frame in its final converged state, disable pointer warp, and show terminal output pre-typed. Everything must still look complete and intentional.

## PAGE STRUCTURE (top to bottom)

### 1. Nav
Slim, sticky, blurred `--bg` at 80% with hairline bottom border. Left: ASCII wordmark `TaskBridge` (small monospace, `--paper`) plus a `● live` amber dot. Right: anchor links (Why · Features · Quickstart · Demo · FAQ), GitHub icon-link with star count fetched from the GitHub API (`Parithosh-Varma/TaskBridge`) with a hardcoded sensible fallback if the fetch fails.

### 2. Hero — "the convergence"
- **Canvas ASCII art: the pipeline.** Diffuse ember-tinted noise field enters from the left, converges through a narrowing ASCII channel (rendered as `[═]` style brackets that tighten with scroll), and exits right as calm structured green lines — the visual metaphor: *unstructured intent → durable queue → verified work*. Mouse proximity creates a soft swirl/distortion.
- Headline (JetBrains Mono, tight): **"Claude plans. OpenCode builds."**
- Sub: *"Dispatch real coding work from Claude to headless OpenCode agents via a durable SQLite queue. Structured results, git-aware diffs, receipts."*
- **Install block:** the one-liner in a bordered terminal-style card with a copy button (success state swaps the icon to a check + "Copied" for 1.5s):
  ```
  git clone https://github.com/Parithosh-Varma/TaskBridge.git && cd TaskBridge && ./install.sh
  ```
- Two CTAs: primary amber-bordered **"★ Star on GitHub"**, secondary ghost **"Read the docs →"** (anchors to Quickstart).
- Below the fold edge: a quiet scroll hint — `▼ scroll` with a slow pulse; it fades once the user scrolls.

### 3. Why — "out of context"
Two-column prose block with asymmetric layout (not a 50/50 card grid). Left: heading + the problem in prose. Right: three stacked mini-rows, each a single ASCII glyph (`▣` planner, `▤` executor, `⛁` the queue) with a sentence each. Lines drawn from the README's "Why this exists": Claude can't touch your filesystem; OpenCode lives outside Claude's context; the bridge closes the loop. Close the section with the pull-quote, set in `--signal`: **"Claude stays the interface. OpenCode does the execution. SQLite is the durable handoff."**

### 4. Architecture — "the scrolling diagram"
`AsciiScene` pinned or progress-driven: as the reader scrolls through a tall section, the entire architecture *draws itself* left to right, character by character:

```
Claude ──MCP──▶ [opencode_bridge_mcp.py] ──write──▶ ⛁ tasks.db
                                                       ▲      │
                          [tasks_cli.py / worker.py] ──┘      ▼
                                    │                  ~60s, priority, oldest-first
                                    ▼
                        ┌─ opencode run ─ worktree ─┐
                        │  edits · shell · tests    │
                        └──── structured result ────┘
                                    │
                                    ▼
                   { summary, files_touched, tests_run, open_questions } + diff
                                    │
                                    ▼
                        Claude: get_task_result
```

Each stage reveals in sequence with a 1-line caption in `--faint` appearing beneath the active element (e.g. "durable queue survives restarts — retries, priorities, dependencies, two-way questions"). On completion, the whole diagram holds, then recedes as you continue. Also give it the reverse arrow: `OpenCode ──claude_ask──▶ Claude` as a dashed line back.

### 5. Features — "the spec sheet"
Not a generic card grid. A **ledger**: full-width rows separated by hairlines, each row = tiny ASCII icon (2-char glyph, e.g. `▤ ▣ ⛁ ⟲ ⚑ ⊞`), title in mono, 1–2 line description, and where applicable a right-aligned mono chip showing the relevant tool names (`submit_batch`, `wait_for`, `answer_task`). Rows reveal with a staggered fade-up (`motion`), 40ms apart. Source rows from the README Features list — cover: 16 MCP tools, headless auto-worker (~60 s), two-way questions with macOS banner, worktree isolation, honest permissions (`readonly` reverts, reported), reverse bridge (6 tools), public-URL mode, live dispatch board, caller detection, production reliability (timeouts, 15-min reaper, flock, heartbeat).

### 6. Quickstart — "three moves"
Numbered `01 / 02 / 03` steps, terminal-card styling, each with a copyable command block:
1. `git clone … && cd TaskBridge && ./install.sh` — installs deps, token, tunnel, prints your connector box
2. Expected output block: public URL + bearer token (render as ASCII box, dimmed, with `•••` for the token)
3. From Claude: `submit_task(...)` → `wait_for(...)` → `get_task_result(...)` → `{summary, diff, usage}`
Side note in `--faint`: prerequisites — Python 3.12, `opencode` on PATH, free ngrok account. Link to full README.

### 7. Demo — two halves, one section
**Left: the scroll-typed terminal.** A terminal card whose contents type themselves as the section scrolls into view (pause typing when off-screen). Sequence: submit a task → `waiting` state appears with an ASCII question block → `answer_task` → run resumes → structured result + git diff summary renders. Use realistic-but-clearly-illustrative content based on README examples.
**Right: the ASCII dispatch board mock.** A stylized version of `bridge_dashboard.html` rendered in pure ASCII/box-drawing: tally counts (pending/running/waiting/done) that scramble-then-settle when they enter the viewport, a worker lamp `● ONLINE`, a fake live log feed of 5–6 lines that scrolls with a subtle cadence. Caption beneath: *"this is a real view — the actual board ships at `GET /` on the same host."*

### 8. FAQ — accordion
Native details/summary or an accessible custom accordion; chevron rotates, panel height animates, one open at a time. Content from the README's Troubleshooting: 421 behind tunnel; tunnel URL changed; worker looks stuck; double-run after kill (summarize honestly, including the ppid-walk note); no banners; reverse bridge fails fast (run `claude login`); `opencode` not found.

### 9. Limitations — "receipts"
Deliberately does NOT hide weakness. A bordered section with `--faint` border styling, heading **"What it won't do"**. Four concise items from the README: token counts aren't exposed by the CLI; `no-network`/`no-shell` are prompt-level, not OS-enforced; macOS-specific scheduling & banners (Linux needs systemd/cron); ~60 s pickup cadence means up to a minute of latency, tasks up to 1800 s. Lead with a one-liner: *"Every bridge has a load limit. Here's ours, up front."*

### 10. Final CTA + footer
Big, centered, quiet: `◆` ASCII mark, **"Fork it. Self-host it. Build on it."** — Apache-2.0. Primary star CTA again, secondary `git clone` one-liner. Footer: project structure as a tiny mono two-column list, GitHub link, license line, and the tagline `Claude plans. OpenCode builds.` Everything `--faint` and small.

## ANIMATION & SCROLL CRAFT

- All reveals: `IntersectionObserver`-triggered once, `translateY(14px) → 0` + opacity, 400–600ms, custom cubic-bezier — snappy-out, never bouncy.
- Scroll-linked effects (the ASCII convergence, the architecture reveal, terminal typing, dashboard scramble) are driven by section progress — tie to `scrollYProgress` via `motion`'s `useScroll`, not raw scroll listeners.
- Mouse-reactive effects: pointer position lerped at ~0.06/frame, only within hero + demo canvases.
- `prefers-reduced-motion`: everything above collapses to static final states. This is non-negotiable.
- Density change: on viewports under 768px, halve ASCII cell resolution, drop pointer effects (touch), and stack all asymmetric layouts. The hero headline must still hit above the fold on a 390×844 phone.

## COPY RULES

- Every technical claim traces to the README. If a number appears on the page (16 tools, 6 reverse tools, 60 s, 1800 s, 20-task batches, 15-min reaper), it appears in the README.
- Tone: precise, warm, confident, self-aware. Short declarative sentences. Speak of "work" the way the README does: tasks, receipts, dispatches.
- No superlatives ("blazing", "revolutionary", "seamless"), no exclamation marks, no emoji in copy. `★ ● ◆ ─` as typographic marks are fine; emoji are not.
- Do not use the word "AI-powered". Ever.

## ACCESSIBILITY & QUALITY FLOOR

- Semantic landmarks: `header/nav/main/section/footer`, one `h1`, sequential headings.
- Copy buttons: real `<button>`s with `aria-live="polite"` confirmation. Accordion: `aria-expanded` + keyboard operable. Focus states: 2px `--signal` outline, 2px offset (matches the dashboard).
- Contrast: body text on `--bg` must clear WCAG AA; `--faint` is for ≥14px meta text only.
- No layout shift: fonts via `next/font` with `display: swap`; canvases get explicit aspect-ratio boxes.
- `npm run build` clean. No `any` leaked into public APIs. Console clean in dev.
- SEO: proper metadata, OpenGraph tags, title `TaskBridge — Claude plans. OpenCode builds.`, description from the README one-liner, and a simple generated OG image route (`app/opengraph-image.tsx`) rendering the wordmark + tagline on the dark theme.

## WORKING PROCEDURE FOR YOU (the builder)

1. Read `README.md` fully. Write a 15-line `landing/CONTENT.md` mapping every page section → README source lines. This is your contract; follow it.
2. Scaffold the app. Set up tokens, fonts, grain, base layout.
3. Build the ASCII engine and the hero scene. Iterate on the hero until it genuinely feels like a premium kinetic art piece — not a demo. This is where most of your effort goes.
4. Build sections in order: nav → why → architecture → features → quickstart → demo → faq → limitations → cta/footer.
5. After each section: run the dev server, check it renders, scroll-check the animations, fix immediately. Never batch bugs.
6. Finish with: production build, a full-page screenshot review pass, reduced-motion pass, and 390px-wide pass. Fix what you find.
7. Report back with: file tree, what you verified, anything you'd flag.

Start now.
