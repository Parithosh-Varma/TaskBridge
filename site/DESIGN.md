# TaskBridge site — design notes

React multipage site (Vite + react-router) that replaces the earlier static HTML version.
Deployed to Cloudflare Pages: `claude-opencode-bridge.pages.dev`.

## Aesthetic

Terminal-native. The chrome recedes; the ASCII is the decoration.

- One typeface: JetBrains Mono, everywhere, no exceptions.
- Ink `#0B0B0C` & ivory `#E8E3D5`; semantic signals only: amber (CTR / identity),
  green (progress), red (failure). No gradients, no glow, no scanlines, no icon cards.
- Everything dense content is real repo data: tools, statuses, config, troubleshooting.

## Signatures

- **Hero**: mouse-reactive bridge art. Two stacked `<pre>` layers (base + amber
  "flashlight" layer); task beads idle-animate across the rails (honors
  `prefers-reduced-motion`).
- **Five-act scrollytelling**: submit → queue → execute → return → ask back.
  One fixed-grid ASCII `<pre>` per timeline position; scroll drives a
  parametric scene (`p ∈ [0,1]`), and acts hand over with a per-cell dither
  dissolve. Sticky stage left, act copy right.
- **Dispatch board demo**: an honest, labeled *simulation* of the real board
  served at `GET /` on the bridge.
- **Manifest + numbers**: all 22 tools (16 claude-side, 6 reverse), and numbers
  the implementation can actually back up.

## Generation

- Figlet banners are pre-rendered at build time: `npm run banners` →
  `src/banners.js` (checked in, no runtime font loading).
- Scenes live in `src/scenes/*.js` as pure functions of scroll phase —
  preview tunables with `site/scripts/preview.mjs`.
- `scripts/diagnose.mjs` + `scripts/shot.mjs` drive system Chrome via
  playwright-core to verify mount + take viewport screenshots.

## Hard-won lessons (do not regress)

1. **Router basename ≠ vite base.** vite's `base: './'` is for *asset URLs* only.
   Passing `import.meta.env.BASE_URL` (== `'./'` in a build) to
   `<BrowserRouter basename>` makes the router silently match **nothing** —
   React paints an empty tree with **zero console errors**. Guarded in
   `main.jsx`: basename is forced to `'/'` when BASE_URL is relative.
2. **ASCII must fit the content box.** `clientWidth` includes padding/borders;
   font fitting uses `innerClientWidth()` (padding + border subtracted).
3. **Cloudflare Pages: files win over `_redirects`.** Legacy static files
   (`faq.html` etc.) from a previous deployment shadow SPA routes because
   `200`-rewrite redirects don't override existing assets. The only clean fix
   is a fresh project (or ${when} deleting each orphan path). The project was
   reset once in Oct 2026 for exactly this reason; keep `dist/` the sole source
   of truth so it doesn't recur.
4. `_headers` needs `style-src 'unsafe-inline'` because React writes style
   attributes (ASCII font sizing) directly.

## Recovery

The whole `site/` tree is committed to git. If it is ever deleted (it has
happened — a parallel process `rm -rf`ed the directory mid-session), recover
with `git checkout -- site/` — that is exactly why it is committed now.
