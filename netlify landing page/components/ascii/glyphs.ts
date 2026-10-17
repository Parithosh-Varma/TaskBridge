// Glyph atlas: every (glyph × tone × alpha) combination pre-rendered once,
// so a frame is nothing but drawImage blits from one texture.

/** Brightness ramp, dark → bright. Index 0 is an empty cell. */
export const RAMP = " ·:-=+*#%@";

/** Structural glyphs a field can request explicitly via `glyph`. */
export const EXTRA = "═[]╪╲╱─━·▸";

export const GLYPHS = RAMP.slice(1) + EXTRA;

/** Index into GLYPHS for an EXTRA glyph. */
export function glyphIndex(ch: string): number {
  const i = GLYPHS.indexOf(ch);
  if (i < 0) throw new Error(`glyph "${ch}" is not in the atlas`);
  return i;
}

export const TONES = 24;
export const ALPHAS = [0.22, 0.36, 0.52, 0.68, 0.84, 1] as const;

type RGB = readonly [number, number, number];

/** ember → signal → seal: planning heat → dispatch → execution done. */
const STOPS: readonly RGB[] = [
  [0xe2, 0x60, 0x3a],
  [0xf2, 0xa0, 0x07],
  [0x8f, 0xc3, 0x9a],
];

export function rampRGB(t: number): RGB {
  const x = Math.min(0.9999, Math.max(0, t)) * (STOPS.length - 1);
  const i = Math.floor(x);
  const f = x - i;
  const a = STOPS[i];
  const b = STOPS[i + 1];
  return [a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f, a[2] + (b[2] - a[2]) * f];
}

export interface GlyphAtlas {
  canvas: HTMLCanvasElement;
  /** Device-pixel size of one atlas cell. */
  w: number;
  h: number;
}

export function buildAtlas(cellW: number, cellH: number, dpr: number, fontFamily: string): GlyphAtlas {
  const w = Math.ceil(cellW * dpr);
  const h = Math.ceil(cellH * dpr);
  const canvas = document.createElement("canvas");
  canvas.width = w * GLYPHS.length;
  canvas.height = h * TONES * ALPHAS.length;
  const ctx = canvas.getContext("2d");
  if (!ctx) return { canvas, w, h };

  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.font = `500 ${Math.round(cellH * 0.86 * dpr)}px ${fontFamily}`;

  for (let tone = 0; tone < TONES; tone++) {
    const [r, g, b] = rampRGB(tone / (TONES - 1));
    for (let a = 0; a < ALPHAS.length; a++) {
      const row = tone * ALPHAS.length + a;
      ctx.fillStyle = `rgba(${r | 0},${g | 0},${b | 0},${ALPHAS[a]})`;
      // Glow is earned: only the brightest alpha band gets a halo.
      const glow = a === ALPHAS.length - 1;
      ctx.shadowColor = glow ? `rgba(${r | 0},${g | 0},${b | 0},0.55)` : "transparent";
      ctx.shadowBlur = glow ? 6 * dpr : 0;
      for (let gi = 0; gi < GLYPHS.length; gi++) {
        ctx.fillText(GLYPHS[gi], gi * w + w / 2, row * h + h / 2 + dpr * 0.5);
      }
    }
  }
  return { canvas, w, h };
}
