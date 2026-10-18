# Hyperframes Composition Brief: TaskBridge

## Objective
Create a short launch-style brag video for TaskBridge (landscape, 20.0s):
a dry, terminal-native dispatch receipt where Claude submits a task, an OpenCode
auto-worker picks it up, pauses with a real question, gets an answer, and returns a diff.

## Output
- Composition directory: `brag-output/composition/`
- Rendered video: `brag-output/brag.mp4`
- Format: landscape — 1920x1080
- Duration: 20.0 seconds (hard window: 15–25s)

## Source Material
- Project root: `/Users/varma/Downloads/TaskBridge`
- Primary files read:
  - `netlify landing page/lib/content.ts` (TERMINAL_SCRIPT, BOARD_FEED, FEATURES, install one-liner)
  - `netlify landing page/app/globals.css` (palette, fonts, ASCII chrome, grain)
  - `netlify landing page/components/sections/Hero.tsx` (hero lines, eyebrow, marks, ramp text)
  - `netlify landing page/components/sections/Demo.tsx` + `DemoTerminal.tsx` + `DispatchBoard.tsx`
  - `netlify landing page/components/ui/ClaudeMark.tsx`, `OpenCodeMark.tsx` (real brand marks)
  - `README.md`, `site/DESIGN.md`
  - `netlify landing page/public/screenshot-overview.webp` (real dispatch board)
- Product name: TaskBridge
- Tagline / strongest claim: `Claude plans. OpenCode builds.`
- Key UI moment to recreate: the demo terminal session (submit → question → answer →
  receipt) plus the live dispatch board's tallies and docket chips
- Copy that must appear verbatim:
  - `Claude plans.` / `OpenCode builds.`
  - `MCP task bridge / SQLite queue / Apache-2.0`
  - `submit_task(title="Add retry tests",` / `working_dir="~/code/target-repo")`
  - `<- { id: "t_0142", status: "pending" }`
  - `* claimed | branch + worktree created`
  - `* opencode run | streaming task_logs/t_0142.log`
  - `! waiting -- the worker has a question`
  - `Retries: keep the fixed delay, or` / `switch to exponential backoff?`
  - `answer_task(task_id="t_0142", answer="Keep the fixed delay.")`
  - `* resumed with the answer in context`
  - `summary  Added retry tests for task_store`
  - `files_touched  tests/test_retries.py`
  - `tests_run  pytest -q · 14 passed`
  - `diff  tests/test_retries.py +48 -0`
  - `PENDING` / `COMPLETED` chips, `FILED` tally, `DISPATCH BOARD`
  - `curl -fsSL https://taskbridge-landing.pages.dev/install | bash`
  - `Apache-2.0 — fork it, self-host it.`

## Local assets provided (copy into `composition/assets/` as needed)
- `assets/logo-mark-cream.png` — cream + amber arrow wordmark mark, transparent, for dark ground
- `assets/fonts/jbm-box.woff2` — JetBrains Mono box-drawing subset from the site (`─│┌┐└┘└┘`) so ASCII chrome keeps exact advance widths

## Creative Direction
- Tone preset: `polished`
- Creative direction: "terminal-native dispatch receipt — the product's own demo
  terminal and board, dry and precise, no hype, no mascots"
- Interpretation: restraint over energy. Big mono type, generous holds, hard cuts
  between beats instead of bouncy transitions. Motion is limited to typing, printing,
  a docket chip flipping, and one tally ticking. The humor is the product's honesty —
  a worker that stops to ask, a receipt with an empty `open_questions: []`. Nothing winks.
- Angle: one task's lifecycle, shown as a receipt. The product's own session is the script.
- Hook: `Claude plans.` / `OpenCode builds.` typed character by character with the real
  Claude sunburst and OpenCode block marks, "builds." in the ramp gradient.
- Outro / punchline: cream arrow mark + `TaskBridge`, the install one-liner in amber,
  then `Apache-2.0 — fork it, self-host it.` Long hold, fade.
- Avoid:
  - Generic SaaS language ("streamline your workflow", "supercharge", "10x")
  - Abstract filler visuals, waveforms, particles, glow-speak
  - Redesigning the product's look: stay inside `#100c08` warm-dark ground, mono type,
    box-drawing chrome, and the four semantic signals
  - Inventing numbers, quotes, or features not in the repo

## Visual Identity
- Background: `#100c08`; panels `#1a140e`, `#221a12`; lines `#33291d`
- Text: `#efe4cc` (paper, 80% for secondary); faint `#9c8c72`
- Accents: ember `#e2603a`, signal `#f2a007`, seal `#8fc39a`, wait `#b9a3e3`
- Display font: JetBrains Mono (eyebrows 11px uppercase tracking 0.22em; hero 62–72px
  extrabold tracking −0.045em)
- Body font: Newsreader (serif) — used for exactly one closing line in the outro
- Visual references from the project:
  - terminal card: 1px `#33291d` border, `┌ ┐ └ ┘` corner ticks, `─` rules, `> ` prompt in `#f2a007`
  - dispatch board: tally row (RUNNING / PENDING / WAITING / FILED) with tabular numbers,
    docket cards with bordered chips, `* worker online` lamp in signal amber
  - ramp gradient `linear-gradient(90deg, #e2603a, #f2a007 50%, #8fc39a)` on "builds."
  - teletype grain at ~3.5% opacity (optional, keep very subtle)
  - Claude sunburst mark `#d97757`, OpenCode block mark in paper

## Storyboard
Use `brag-output/brag-plan.md` as the creative contract. Scene boundaries and durations:

1. **Hook: plans / builds** — 0.00–3.01 (3.01s) — eyebrow, `Claude plans.` typed, `OpenCode builds.` typed with ramp, settled hold.
2. **Entry: submit** — 3.01–6.28 (3.27s) — terminal card arrives; typed `submit_task(...)`; return line prints; docket row + `PENDING` chip.
3. **Key action: the question** — 6.28–12.56 (6.28s) — two status lines; `! waiting --` in wait color; box-drawn question card lands and **holds settled 8.0–10.2 with no SFX**; `answer_task(...)` types; `* resumed with the answer in context` prints.
4. **Result: the receipt** — 12.56–16.93 (4.37s) — `+ done` in seal; docket flips to `COMPLETED`; FILED tally ticks 29→30; four result rows land and hold as a set.
5. **Outro** — 16.93–20.00 (3.07s) — mark + `TaskBridge`; install one-liner types; closing serif line; fade out.

Scenes 2–4 are **one continuous session inside one persistent terminal card** — the card
must not re-enter between them. The board panel sits to the right of the card from
scene 2 onward and mutates in scenes 2 and 4.

## Audio
- Audio role: warm bed + sparse professional accents; the sound of a machine working.
- Audio arc: music in under the hook → steady through submit → dip under the question
  hold → back up for the receipt → fade out under the outro.
- Music: `happy-beats-business-moves-vol-10-by-ende-dot-app.mp3` (copy already staged)
- Music treatment: 0.6s fade-in; bed at 0.30; dip to ~0.22 between 7.8 and 10.2;
  back to 0.30 at 10.4; fade to silence over 18.8–20.0, never above 0.35.
- Music cue guidance: bundled preset
  `<skill-dir>/assets/music/cues/happy-beats-business-moves-vol-10-by-ende-dot-app.music-cues.json`
  — 109.96 BPM, beat grid from 0.27. Strong cues in window: 15.82 (0.96), 18.01 (0.97),
  18.55 (0.98). Intended locks: install one-liner lands ~18.55 (±0.15), receipt
  completion payoff ~15.82 (±0.15), question-card land near beat 7.79 or 8.22 (±0.10).
  Entrance beats: 3.01 (scene 2), 6.28 (scene 3), 12.56 (scene 4), 16.93 (scene 5).
  Do NOT reveal anything on the beats under the question hold (8.73–10.38): that hold
  is deliberately still.
- Audio-reactive treatment: subtle — the board's `* worker online` lamp and the terminal
  card's border warmth breathe with music RMS/bass. No waveform, equalizer, or particle visuals.
- Audio-coupled moments:
  - hook typing — randomized keypresses; soft impact when `builds.` lands
  - submit — keypresses; soft drop as the return line prints; click for the `PENDING` chip
  - question card — one soft impact; **silence through the hold**; keypresses for the answer line
  - receipt — bell/impact on `+ done`; chip/switch sound on the docket flip; chip tick for the tally; soft drops for the rows
  - outro — one restrained impact under the mark; nothing else
- SFX selection guidance: match motion to sound; keyboard set for per-character typing;
  soft/medium family sounds for rows and chips; one bell-class hit for `+ done`.
- SFX analysis guidance: `/Users/varma/.claude/skills/brag/assets/sfx/sfx-analysis.md`
- Exact SFX choice: Hyperframes chooses filenames, timestamps, density, and volume from
  the implemented animation. Prefer low/medium high-frequency-risk files.

## Hyperframes Instructions
Load the composition-building Hyperframes domain skills — `hyperframes-core`,
`hyperframes-animation`, `hyperframes-creative`, `hyperframes-keyframes`,
`hyperframes-cli`. /brag is its own workflow: do not enter the `hyperframes` entry-point
intent interview and do not route into its generic promo/launch-video workflow.

Requirements:
- Show real product material: the terminal session and the dispatch board are both
  recreated from the project's own copy — no invented UI.
- Keep every line readable in the final render; text holds must satisfy the plan's holds.
- Scenes 2–4 share one persistent terminal card (single take, no re-entry).
- Total duration exactly 20.0s (±0.1s).
- Music + SFX included as described; music file `assets/music/happy-beats-business-moves-vol-10-by-ende-dot-app.mp3`.
- `npx hyperframes check` must pass with zero errors before render.
- Render locally with `npx hyperframes render --output ../brag.mp4`.
- Creation and rendering stay local; no publishing.
