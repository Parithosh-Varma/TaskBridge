import { fbm, fract, lerp, noise2, smoothstep } from "./noise";
import { glyphIndex } from "./glyphs";
import type { AsciiField } from "./types";

const G_WALL = glyphIndex("═");
const G_OPEN = glyphIndex("[");
const G_CLOSE = glyphIndex("]");
const G_TICK = glyphIndex("╪");
const G_DOWN = glyphIndex("╲");
const G_UP = glyphIndex("╱");
const G_LANE = glyphIndex("─");
const G_PACKET = glyphIndex("━");
const G_DOT = glyphIndex("·");
const G_HEAD = glyphIndex("▸");

function channelWidth(
  u: number,
  funnelStart: number,
  throatX: number,
  throatEnd: number,
  fanEnd: number,
  throatW: number,
  exitW: number,
): number {
  if (u < funnelStart) return 0.95;
  if (u < throatX) return lerp(0.95, throatW, smoothstep(funnelStart, throatX, u));
  if (u < throatEnd) return throatW;
  return lerp(throatW, exitW, smoothstep(throatEnd, fanEnd, u));
}

/**
 * The convergence. Diffuse ember noise on the left is drawn into a narrowing
 * `[═══]` channel (tighter as the hero scrolls), and leaves on the right as calm,
 * structured seal-green lanes: unstructured intent → durable queue → verified work.
 */
export const heroField: AsciiField = (i, o) => {
  const { u, vn, t, progress, intro, rows, cols, compact } = i;
  const throatX = compact ? 0.46 : 0.6;
  const funnelStart = throatX - (compact ? 0.3 : 0.27);
  const throatEnd = throatX + (compact ? 0.12 : 0.085);
  const fanEnd = throatEnd + (compact ? 0.18 : 0.15);
  const throatW = Math.min(0.92, lerp(0.36, 0.11, smoothstep(0, 0.8, progress)) + (1 - intro) * 0.55);
  const exitW = compact ? 0.72 : 0.62;
  const rowH = 2 / rows;
  const av = vn < 0 ? -vn : vn;
  const w = channelWidth(u, funnelStart, throatX, throatEnd, fanEnd, throatW, exitW);

  // ── Channel walls ───────────────────────────────────────────────
  const wallReach = funnelStart + (throatEnd - funnelStart + 0.02) * intro;
  if (u > funnelStart + 0.03 && u <= throatEnd + 0.004 && u <= wallReach && av >= w) {
    const wNext = channelWidth(u + 1 / cols, funnelStart, throatX, throatEnd, fanEnd, throatW, exitW);
    const slope = Math.abs(wNext - w) / rowH;
    if (av < w + rowH * Math.max(1, slope)) {
      const col = Math.round(u * (cols - 1));
      const c0 = Math.round(throatX * (cols - 1));
      const c1 = Math.round(throatEnd * (cols - 1));
      const pulse = smoothstep(0.78, 1, fract(u * 3.2 - t * 0.42));
      o.b = 0.6 + pulse * 0.32;
      o.tone = 0.4 + pulse * 0.08;
      if (col === c0) o.glyph = G_OPEN;
      else if (col === c1) o.glyph = G_CLOSE;
      else if (col > c0 && col < c1) o.glyph = (col - c0) % 6 === 0 ? G_TICK : G_WALL;
      else o.glyph = slope < 0.45 ? G_WALL : vn < 0 ? G_DOWN : G_UP;
      return;
    }
  }

  const sy = vn / w;
  const inside = av < w;
  const structure = smoothstep(funnelStart - 0.1, throatEnd, u);

  // ── Flow: intent, drifting right, compressed by the channel ─────
  let flow = 0;
  let n = 0.5;
  if (u < fanEnd) {
    const sv = inside ? sy : vn;
    n = fbm(u * 6.5 - t * 0.42, sv * 1.7 + t * 0.06, 3);
    const diffuse = (n - 0.4) * 2.2;
    const streak = smoothstep(0.6, 0.92, noise2(u * 26 - t * 2.4, sv * 6.5 + 11.3));
    flow = diffuse * (1 - structure * 0.55) + streak * (0.25 + structure * 0.8);
    flow *= lerp(0.5, 1.15, smoothstep(0, throatX, u));
    if (inside) {
      flow *= u > funnelStart ? smoothstep(1, 0.72, Math.abs(sy)) : 1;
    } else {
      // Outside the funnel, the field thins out as it is drawn in.
      flow *= 1 - smoothstep(funnelStart, throatX - 0.04, u);
    }
    // The compressed core: denser and hotter the tighter the channel gets.
    if (inside && u > funnelStart) {
      const core = smoothstep(funnelStart + 0.05, throatX, u) * (1 - smoothstep(throatEnd, fanEnd, u));
      flow += core * (0.22 + 0.42 * n) * (1 - sy * sy) * lerp(0.8, 1.2, smoothstep(0.36, 0.11, throatW));
    }
    if (u > throatX && u < throatEnd) flow *= 1.15;
    if (u > throatEnd) flow *= 1 - smoothstep(throatEnd, fanEnd, u);
    flow *= smoothstep(0, 0.14, u) * (0.55 + 0.45 * intro);
  }

  if (u < throatEnd) {
    o.b = flow;
    o.tone = lerp(0.02, 0.5, smoothstep(0.04, throatEnd, u)) + (n - 0.5) * 0.14;
  } else {
    // ── Exit: structured lanes, packets moving right ─────────────
    const lanes = compact ? 5 : 7;
    const half = (lanes - 1) / 2;
    const k = Math.round((vn / w) * half);
    const laneReach = throatEnd + (1.02 - throatEnd) * intro;
    o.b = flow;
    o.tone = 0.6 + structure * 0.3;
    if (Math.abs(k) <= half && u <= laneReach) {
      const laneVn = (k / half) * w;
      if (Math.abs(vn - laneVn) < rowH * 0.5) {
        const speed = 0.13 + 0.035 * (((k + 7) * 5) % 3);
        const ph = fract(u * 2.3 - t * speed + k * 0.381);
        const len = 0.11;
        const edge = 1 - smoothstep(0.93, 1, u) * 0.55;
        if (ph < len) {
          o.b = 0.96 * edge;
          o.glyph = ph > len * 0.86 ? G_HEAD : G_PACKET;
          o.tone = 0.93;
        } else {
          o.b = Math.max(flow, (0.3 + 0.08 * smoothstep(0.7, 1, fract(u * 9 - t * 0.6))) * edge);
          o.glyph = G_LANE;
          o.tone = 0.84 + smoothstep(throatEnd, fanEnd, u) * 0.16;
        }
      }
    }
    if (o.glyph < 0 && o.b < 0.1 && noise2(i.x * 1.7 + t * 0.25, i.y * 1.3) > 0.86) {
      o.b = 0.2;
      o.glyph = G_DOT;
      o.tone = 0.9;
    }
  }

  // Vertical vignette keeps the edges quiet.
  o.b *= 1 - 0.6 * smoothstep(0.72, 1.02, av);
};

/** Engine tail for the dispatch board strip: a slow carrier wave, signal → seal. */
export const engineField: AsciiField = (i, o) => {
  const { u, vn, t } = i;
  const n = fbm(u * 5 - t * 0.5, vn * 0.8 + t * 0.15, 2);
  const wave = Math.sin(u * 11 - t * 1.4) * 0.5 * (0.55 + n * 0.7);
  const d = Math.abs(vn - wave);
  o.b = Math.max(0, 1 - d * 1.8) * 0.78 + Math.max(0, n - 0.58) * 0.9;
  o.b *= smoothstep(0, 0.06, u) * (1 - smoothstep(0.94, 1, u));
  o.tone = 0.35 + u * 0.6;
};

/** Settled lanes behind the final call to action; the centre is kept clear for type. */
export const calmField: AsciiField = (i, o) => {
  const { u, vn, t, y, progress, aspect } = i;
  const du = u - 0.5;
  const dv = vn * aspect;
  const e = (du * du) / 0.09 + (dv * dv) / 0.035;
  const mask = smoothstep(0.55, 1.6, e);
  if (mask <= 0) return;
  const reach = 0.15 + progress * 0.9;
  if (Math.abs(du) * 2 > reach) return;
  if (y % 3 === 1) {
    const ph = fract(u * 1.8 - t * (0.05 + (y % 5) * 0.012) + y * 0.17);
    if (ph < 0.07) {
      o.b = 0.62 * mask;
      o.glyph = G_PACKET;
    } else {
      o.b = 0.2 * mask;
      o.glyph = G_LANE;
    }
    o.tone = 0.2 + u * 0.75;
    return;
  }
  const n = fbm(u * 9 + t * 0.05, vn * 2 - t * 0.04, 2);
  o.b = Math.max(0, n - 0.6) * 1.1 * mask;
  o.tone = 0.25 + u * 0.7;
};
