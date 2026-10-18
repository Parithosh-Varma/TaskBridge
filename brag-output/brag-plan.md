# Brag Plan: TaskBridge

## What is this app?

TaskBridge is an MCP + SQLite task queue that lets Claude dispatch real coding work
to headless OpenCode agents in isolated git worktrees — and get back a structured
result, a git-aware diff, live logs, and the answer to a question the worker asked
mid-run. "Claude plans. OpenCode builds."

## The angle

A dev tool that is *honest* about what it is: a queue, a worker, a receipt — no
dashboards-as-marketing, no "streamline your workflow." The video is a **dispatch
receipt**: one task submits, one worker picks it up, the worker asks a real question
mid-run, Claude answers it, and the diff comes back. The product's own terminal
session and its own dispatch board are the entire set. The dry, terminal-native
aesthetic does the bragging; the claim is verifiable on screen.

## Hook (first 2-3 seconds)

`Claude plans.` / `OpenCode builds.` — typed, character by character, with the real
Claude sunburst mark and OpenCode block mark, "builds." in the site's ember→signal→seal
ramp. The product's own hero line, typed as if it were a command. It states the
whole two-agent premise in four words before the viewer can leave.

## Key moments (the middle)

- **The queue accepts.** `submit_task(...)` types out and returns
  `{ id: "t_0142", status: "pending" }` — and a docket row appears on the dispatch
  board with a PENDING chip, exactly like the board at `GET /`.
- **The worker asks a question — the signature moment.** Status lines stream
  (`claimed | branch + worktree created`, `opencode run | streaming task_logs/t_0142.log`),
  then `! waiting -- the worker has a question` in the wait color, and a box-drawn
  question card lands: *"Retries: keep the fixed delay, or switch to exponential
  backoff?"* Claude answers with `answer_task(...)`, and the run resumes with the
  answer in context. Nobody else has this beat.
- **The receipt.** `+ done` slams in green, the board row flips to COMPLETED and the
  FILED tally ticks from 29 to 30, then the structured result prints: summary,
  files touched, tests run, and `diff tests/test_retries.py +48 -0`.

## Outro / punchline

The cream arrow mark, then `TaskBridge` in mono. The install one-liner types:
`curl -fsSL https://taskbridge-landing.pages.dev/install | bash`. Under it, quietly:
`Apache-2.0 — fork it, self-host it.` Long hold. Cut.

## User flow worth showing

Entry → key action → result, straight from the repo's own demo session:

1. **Entry** — Claude submits a task over MCP; it lands in the SQLite queue as
   `pending` and shows up as a docket on the dispatch board.
2. **Key action** — the auto-worker claims it in ~60 s, runs `opencode run` in a
   worktree, and **pauses with a real question**; Claude answers via `answer_task`
   and the run resumes.
3. **Result** — `get_task_result` returns summary, files touched, tests run, open
   questions, plus a git-aware diff; the docket flips to COMPLETED and the tally counts up.

Scenes 2–4 are one continuous terminal session inside one persistent card, so the
whole flow reads as a single long take with beats — not three separate slides.

## Tone

- Preset: `polished`
- Creative direction: "terminal-native dispatch receipt — the product's own demo
  terminal and board, dry and precise, no hype, no mascots"
- Interpretation: restraint over energy. Big mono type, generous holds, hard cuts
  between beats instead of bouncy transitions, motion limited to typing, printing,
  and one tally tick. The humor is the product's own honesty — a worker that stops
  to ask, a receipt with an empty `open_questions: []`. Nothing winks.

## Format: landscape — 1920x1080
## Duration: 20.0s

## Visual identity (from the project)

- Background: `#100c08` (dark) — panel `#1a140e`, panel-2 `#221a12`, line `#33291d`
- Text: `#efe4cc` (paper) — faint `#9c8c72`
- Accents: ember `#e2603a`, signal `#f2a007`, seal `#8fc39a`, wait `#b9a3e3`
- Display/mono font: JetBrains Mono (everything terminal, chrome, headings)
- Body font: Newsreader (serif) for the one prose line in the outro only
- Strongest visual elements: the terminal card with `┌ ┐ └ ┘` box-drawing chrome and
  the `─` rules; the dispatch board with RUNNING / PENDING / WAITING / FILED tallies
  and docket chips; the cream-arrow logo mark; the ramp text gradient
  (`linear-gradient(90deg, #e2603a, #f2a007 50%, #8fc39a)`)
- Real brand marks: Claude sunburst (`#d97757`) and OpenCode block mark, inlined from
  the landing page components

## Share copy (draft)

> Claude plans. OpenCode builds. TaskBridge lets Claude dispatch real coding work to
> headless OpenCode agents over MCP — durable SQLite queue, worktree isolation, live
> logs, a git-aware diff, and a worker that stops mid-run to ask a question. One
> command to self-host.

## Audio direction

- Role: warm bed + sparse professional accents; the sound of a machine working, not
  a hype reel.
- Music: `happy-beats-business-moves-vol-10-by-ende-dot-app.mp3` (60 s, ~110 BPM,
  compact and punchy — dense enough early that a 20 s cut never waits for the groove).
- Music treatment: start at 0 with a 0.6s fade-in under the hook; bed at 0.30 volume,
  dip to ~0.22 under the question card so the pause reads as quiet, back to 0.30 for
  the receipt; 1.2s fade-out under the final logo so the last beat has air.
- Music cue guidance: bundled preset
  `<skill-dir>/assets/music/cues/happy-beats-business-moves-vol-10-by-ende-dot-app.music-cues.json`
  (110 BPM). Strong cues to target: **18.55s** (0.98) for the install one-liner
  landing, **15.82s** (0.96) for the receipt completion beat, and 20.19s is past the
  end so ignore it. Beat grid for entrances: 3.01 (scene 2 start), 6.28 (scene 3 start),
  12.56 (scene 4 start), 16.93 (scene 5 start), 8.73 / 9.29 / 9.83 none — the question
  card should hold through those, do not reveal anything on them. Vol-10's grid also
  carries beats at 10.38, 10.93, 11.47, 12.02 for the answer typing, but do not snap
  typed text to beats — typing has its own rhythm.
- Audio-reactive treatment: subtle. Let the amber "engine alive" lamp on the board and
  the terminal card's border glow breathe with music RMS/bass. No waveform bars, no
  equalizer, no pulsing text.
- SFX posture: sparse and motion-matched; keyboard keypresses are the only "dense"
  element because typing is constant.
- Audio-coupled moments:
  - hook — per-character keypresses (randomized), one soft impact as `builds.` lands
  - submit — keypresses, soft drop as the return line prints, one click as the PENDING chip appears
  - question — soft impact when the question card lands, then **deliberately no cue** during the hold: the silence is the pause
  - answer — keypresses while `answer_task(...)` types
  - receipt — one bell/impact hit on `+ done`, a chip sound as the docket flips to COMPLETED, soft drops for the result rows
  - outro — one restrained impact under the logo, nothing else
- Restraint rule: no SFX during the question hold, no whooshes, no risers, no
  stack of impacts at the end. If a cue would make the pause feel busy, drop it.

## Storyboard

### Scene 1 — Hook: plans / builds — 3.0s (0.00–3.01)
Warm-dark ground `#100c08`. Top-left eyebrow in 11px mono, letter-spaced, faint:
`MCP task bridge / SQLite queue / Apache-2.0` (the site's own hero eyebrow).
Two hero lines, 62-72px mono extrabold, tight tracking, left-aligned like the site:
`Claude plans.` with the real Claude sunburst mark in `#d97757` before the word, and
`OpenCode builds.` with the OpenCode block mark, "builds." in the ramp gradient.
A single `─` rule and `┌ ┐` corner ticks hint at the terminal chrome to come.
Sequential/interaction: yes — eyebrow fades at 0.15, `Claude plans.` types 0.45–1.15,
`OpenCode builds.` types 1.35–2.1, holds settled until 3.0.
Audio intent: quiet, confident, machine-starting-up.
Audio-coupled idea: randomized keypress per character; a soft impact when `builds.`
lands, nothing else.
Music: vol-10 bed, 0.6s fade-in from 0.
Transition mood: hard cut (a 0.12s dip to black) → Scene 2

### Scene 2 — Entry: submit — 3.27s (3.01–6.28)
The terminal card arrives: `#1a140e` panel, 1px `#33291d` border, `┌ ┐ └ ┘` corners,
title row `> taskbridge — claude → queue`. Inside, a `> ` signal-colored prompt and
typed command lines, verbatim from the site's demo session:
`submit_task(title="Add retry tests",` → `  working_dir="~/code/target-repo")`
then the printed return line in faint: `<- { id: "t_0142", status: "pending" }`
On the right, a docket card slides in (the real board's row shape): a `PENDING` chip,
`Add retry tests`, `t_0142`.
Sequential/interaction: yes — card 0.2s, type line 1 from 0.35, line 2 from 1.2,
return line prints 2.1 (holds 1.2s+), docket + chip at 2.5.
Audio intent: the queue accepting something. Bureaucratic, satisfying.
Audio-coupled idea: keypresses; soft drop when the return line prints; one click for the chip.
Music: bed continues.
Transition mood: clean — the card persists, the right-hand panel changes → Scene 3

### Scene 3 — Key action: the worker asks a question — 6.28s (6.28–12.56)
Same card, session continues. Status lines print in faint, fast log cadence:
`* claimed | branch + worktree created` (6.4) then
`* opencode run | streaming task_logs/t_0142.log` (6.9) — with a subtle live-log
shimmer in the card's "engine tail" band (ASCII noise field, faint, no reading load).
At 7.5 everything except the status line dims and `! waiting -- the worker has a
question` prints in `#b9a3e3`. At 7.8 a box-drawn question card draws in
(`┌ question ─┐ … └─┘`, corners and rule animating, wait-colored) containing:
`Retries: keep the fixed delay, or` / `switch to exponential backoff?`
**Holds fully settled 8.0 → 10.2.** The bed dips under this hold; no SFX.
At 10.2 `answer_task(task_id="t_0142", answer="Keep the fixed delay.")` types with
keypresses (finishing ~11.5), then `* resumed with the answer in context` prints
faint at 11.6 and holds to 12.56.
Sequential/interaction: yes — log lines stream one at a time; the question card draws
in; the answer is typed by a cursor. This is the simulation to get exactly right.
Audio intent: tension, then a beat of stillness (the pause), then release.
Audio-coupled idea: drops for the log lines, one soft impact for the question card,
keypresses for the answer. Nothing during the hold.
Music: bed dips to ~0.22 from 7.8 to 10.2, back to 0.30 at 10.4.
Transition mood: hard cut → Scene 4

### Scene 4 — Result: the receipt — 4.37s (12.56–16.93)
`+ done` prints large in `#8fc39a` at 12.6 (beat-lock to the nearest beat; the
15.82s strong cue is the completion payoff, not this line — see cue notes).
The board panel's docket chip flips PENDING → COMPLETED as a chip sound fires, and
the FILED tally ticks 29 → 30 (the board's real counter grows by one — the whole
claim of the video, in a number).
Then the receipt prints in label/value rows, arriving fast and holding as a set:
`summary        Added retry tests for task_store`
`files_touched  tests/test_retries.py`
`tests_run      pytest -q · 14 passed`
`diff           tests/test_retries.py +48 -0`
Rows land 13.1–14.3, full set holds settled to 16.93.
Sequential/interaction: yes — docket flip, tally tick, then four rows one by one.
Audio intent: completion with weight. Not a party — a receipt.
Audio-coupled idea: bell/impact on `+ done`; chip/switch sound on the flip; chip-stack
tick for the tally counting; soft drops for the rows.
Music: bed back to 0.30.
Transition mood: soft crossfade (0.4s) → Scene 5

### Scene 5 — Outro — 3.07s (16.93–20.00)
Ground clears. The cream-arrow mark (`logo-dark.png`) scales in gently at center at
17.1, `TaskBridge` in 56px mono extrabold below it, the display wordmark style of the
site. At 17.9 the install line prints in signal amber:
`curl -fsSL https://taskbridge-landing.pages.dev/install | bash`
**lands with the 18.55s strong cue.** At 18.9 the quiet closing line in Newsreader,
paper at 80%: `Apache-2.0 — fork it, self-host it.` Hold to 20.0, fade out.
Sequential/interaction: yes — mark, wordmark, command typing, closing line.
Audio intent: exhale. One restrained hit under the mark, then the music's last beat
carries the end.
Audio-coupled idea: one restrained impact at 17.1; keypresses for the install line;
music fades out over the final 1.2s.
Music: fade to silence by 20.0.
Transition mood: fade to black (end)

**Music mood for this video:** steady, punchy, business-clean — a machine that works.
**Audio summary:** a warm ~110 BPM bed carries the session; keypresses and small drops
score the typing and printing; one soft impact marks the question, one bell marks
`+ done`, and a dip-to-near-silence under the question hold is the video's only
dramatic pause.

## Grounding notes (what must stay verbatim)

Every claim on screen traces to the repo:
- `Claude plans. OpenCode builds.` — README line 8 / hero h1
- `MCP task bridge / SQLite queue / Apache-2.0` — hero eyebrow
- `submit_task(title="Add retry tests", working_dir="~/code/target-repo")`,
  `{ id: "t_0142", status: "pending" }`, the question card text, `answer_task(...)`,
  `resumed with the answer in context`, `+ done`, the summary/files_touched/tests_run
  block and `diff tests/test_retries.py +48 -0` — the site's own demo session
  (`lib/content.ts`, TERMINAL_SCRIPT), which the page itself labels illustrative
- `claimed | branch + worktree created`, `opencode run | streaming task_logs/t_0142.log`
  — same script
- `PENDING` / `COMPLETED` chips, `FILED` tally, `DISPATCH BOARD` — the real board
  (`screenshot-overview.webp`, `bridge_dashboard.html`)
- `curl -fsSL https://taskbridge-landing.pages.dev/install | bash` — INSTALL_ONE_LINER
- `Apache-2.0 — fork it, self-host it.` — README license section

No secrets, tokens, hostnames, or personal data appear: the board's masked token is
not reproduced, and the local tunnel host is never shown.
