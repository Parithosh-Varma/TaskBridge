/** Per-cell input handed to a field. One object is reused for every cell — never retain it. */
export interface FieldInput {
  /** Cell column / row. */
  x: number;
  y: number;
  cols: number;
  rows: number;
  /** 0..1 across the canvas (after pointer swirl). */
  u: number;
  /** -1..1 top → bottom (after pointer swirl). */
  vn: number;
  /** Vertical half-extent in u units (height / width / 2). */
  aspect: number;
  /** Seconds since mount. */
  t: number;
  /** 0..1 eased intro, reaches 1 after `introSeconds`. */
  intro: number;
  /** 0..1 scroll progress of the owning section. */
  progress: number;
  /** True under 768px. */
  compact: boolean;
}

/** Field output. Reused per cell. */
export interface FieldSample {
  /** Brightness 0..1. */
  b: number;
  /** Position on the ember → signal → seal ramp, 0..1. */
  tone: number;
  /** -1 picks a glyph from the brightness ramp; otherwise an index into GLYPHS. */
  glyph: number;
}

export type AsciiField = (input: FieldInput, out: FieldSample) => void;
