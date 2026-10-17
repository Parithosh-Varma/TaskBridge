"use client";

import { useEffect, useRef, type RefObject } from "react";
import type { MotionValue } from "motion/react";
import { ALPHAS, RAMP, TONES, buildAtlas, type GlyphAtlas } from "./glyphs";
import type { AsciiField, FieldInput, FieldSample } from "./types";

export interface AsciiCanvasOptions {
  field: AsciiField;
  /** Scroll progress of the owning section (0 → 1, entry to exit). */
  progress?: MotionValue<number>;
  /** Element whose pointer movement warps the field. Omit to disable pointer effects. */
  pointerTarget?: RefObject<HTMLElement | null>;
  /** Cell height in CSS px. Width is derived from the glyph aspect. */
  cellSize?: number;
  compactCellSize?: number;
  maxFps?: number;
  introSeconds?: number;
  /** Progress value used for the single static frame under reduced motion. */
  staticProgress?: number;
  /** Seconds of time baked into the static frame. */
  staticTime?: number;
  reducedMotion: boolean;
  /** Pointer spotlight radius in CSS px. */
  pointerRadius?: number;
}

const BAYER4 = [0, 8, 2, 10, 12, 4, 14, 6, 3, 11, 1, 9, 15, 7, 13, 5].map((v) => v / 16 - 0.5);
const LEVELS = RAMP.length - 1;
const COMPACT_QUERY = "(max-width: 767px)";
const FINE_POINTER_QUERY = "(hover: hover) and (pointer: fine)";
const POINTER_LERP = 0.06;

export function useAsciiCanvas(options: AsciiCanvasOptions) {
  const containerRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const optsRef = useRef(options);

  useEffect(() => {
    optsRef.current = options;
  });

  const { reducedMotion } = options;

  useEffect(() => {
    const container = containerRef.current;
    const canvas = canvasRef.current;
    const ctx = canvas?.getContext("2d");
    if (!container || !canvas || !ctx) return;

    const o = optsRef.current;
    const maxFps = o.maxFps ?? 30;
    const frameMs = 1000 / maxFps;
    const compactMq = window.matchMedia(COMPACT_QUERY);
    const fineMq = window.matchMedia(FINE_POINTER_QUERY);

    let atlas: GlyphAtlas | null = null;
    let atlasKey = "";
    let cols = 0;
    let rows = 0;
    let cellW = 0;
    let cellH = 0;
    let dpr = 1;
    let compact = compactMq.matches;
    let visible = false;
    let raf = 0;
    let last = 0;
    const start = performance.now();

    // Pointer, in CSS px relative to the canvas. `pt*` is the target, `p*` the lerped value.
    let ptX = 0;
    let ptY = 0;
    let ptOn = 0;
    let pX = 0;
    let pY = 0;
    let pOn = 0;

    const input: FieldInput = {
      x: 0, y: 0, cols: 0, rows: 0, u: 0, vn: 0, aspect: 0,
      t: 0, intro: 0, progress: 0, compact: false,
    };
    const out: FieldSample = { b: 0, tone: 0, glyph: -1 };

    const fontFamily = () => {
      const v = getComputedStyle(document.documentElement).getPropertyValue("--font-jetbrains").trim();
      return v || "ui-monospace, monospace";
    };

    const layout = () => {
      const rect = container.getBoundingClientRect();
      if (rect.width < 2 || rect.height < 2) return false;
      compact = compactMq.matches;
      dpr = Math.min(2, window.devicePixelRatio || 1);
      cellH = compact ? (optsRef.current.compactCellSize ?? 10) : (optsRef.current.cellSize ?? 14);
      cellW = Math.round(cellH * 0.72);
      cols = Math.ceil(rect.width / cellW);
      rows = Math.ceil(rect.height / cellH);
      canvas.width = Math.round(rect.width * dpr);
      canvas.height = Math.round(rect.height * dpr);
      const key = `${cellW}x${cellH}@${dpr}`;
      if (key !== atlasKey || !atlas) {
        atlas = buildAtlas(cellW, cellH, dpr, fontFamily());
        atlasKey = key;
      }
      return true;
    };

    const draw = (now: number) => {
      if (!atlas) return;
      const opts = optsRef.current;
      const reduced = opts.reducedMotion;
      const t = reduced ? (opts.staticTime ?? 8) : (now - start) / 1000;
      const introS = opts.introSeconds ?? 0;
      const introRaw = reduced || introS === 0 ? 1 : Math.min(1, t / introS);
      const intro = 1 - Math.pow(1 - introRaw, 3);
      const progress = reduced ? (opts.staticProgress ?? 1) : (opts.progress?.get() ?? 0);

      // Lerp pointer toward its target — smooth, never snappy.
      pX += (ptX - pX) * POINTER_LERP * 2;
      pY += (ptY - pY) * POINTER_LERP * 2;
      pOn += (ptOn - pOn) * POINTER_LERP;
      const pointerLive = !reduced && !compact && pOn > 0.01;

      const aw = atlas.w;
      const ah = atlas.h;
      const src = atlas.canvas;
      const dw = cellW * dpr;
      const dh = cellH * dpr;
      const aspect = (rows * cellH) / (cols * cellW) / 2;
      const radius = opts.pointerRadius ?? 170;
      const r2 = radius * radius;

      input.cols = cols;
      input.rows = rows;
      input.aspect = aspect;
      input.t = t;
      input.intro = intro;
      input.progress = progress;
      input.compact = compact;

      ctx.setTransform(1, 0, 0, 1, 0, 0);
      ctx.clearRect(0, 0, canvas.width, canvas.height);

      const invCols = 1 / Math.max(1, cols - 1);
      const pu = pX / (cols * cellW);
      const pvn = (pY / (rows * cellH)) * 2 - 1;

      for (let y = 0; y < rows; y++) {
        const cy = (y + 0.5) * cellH;
        const vnBase = ((y + 0.5) / rows) * 2 - 1;
        for (let x = 0; x < cols; x++) {
          let u = x * invCols;
          let vn = vnBase;
          let spot = 0;

          if (pointerLive) {
            const dx = (x + 0.5) * cellW - pX;
            const dy = cy - pY;
            const d2 = dx * dx + dy * dy;
            if (d2 < r2 * 4) {
              const fall = Math.exp(-d2 / r2) * pOn;
              spot = fall;
              // Swirl: rotate the sample point around the pointer, strongest at the centre.
              const ang = fall * 0.9;
              const cs = Math.cos(ang);
              const sn = Math.sin(ang);
              const du = u - pu;
              const dv = (vn - pvn) * aspect;
              u = pu + du * cs - dv * sn;
              vn = pvn + (du * sn + dv * cs) / aspect;
            }
          }

          input.x = x;
          input.y = y;
          input.u = u;
          input.vn = vn;
          out.b = 0;
          out.tone = 0;
          out.glyph = -1;
          opts.field(input, out);

          let b = out.b + spot * 0.32;
          if (b <= 0.02) continue;
          if (b > 1) b = 1;

          let gi: number;
          if (out.glyph >= 0) {
            gi = out.glyph;
          } else {
            // Ordered dithering across the ramp.
            const q = Math.round(b * LEVELS + BAYER4[((y & 3) << 2) | (x & 3)] * 0.9);
            if (q <= 0) continue;
            gi = (q > LEVELS ? LEVELS : q) - 1;
          }
          const tone = Math.max(0, Math.min(TONES - 1, Math.round((out.tone + spot * 0.08) * (TONES - 1))));
          const ai = Math.min(ALPHAS.length - 1, Math.floor(b * ALPHAS.length));
          ctx.drawImage(src, gi * aw, (tone * ALPHAS.length + ai) * ah, aw, ah, x * dw, y * dh, aw, ah);
        }
      }
    };

    const loop = (now: number) => {
      raf = 0;
      if (!visible || optsRef.current.reducedMotion) return;
      if (now - last >= frameMs - 1) {
        last = now;
        draw(now);
      }
      raf = requestAnimationFrame(loop);
    };

    const kick = () => {
      if (optsRef.current.reducedMotion) {
        draw(performance.now());
        return;
      }
      if (!raf && visible && document.visibilityState === "visible") raf = requestAnimationFrame(loop);
    };

    const relayout = () => {
      if (layout()) {
        draw(performance.now());
        kick();
      }
    };

    const ro = new ResizeObserver(relayout);
    ro.observe(container);

    const io = new IntersectionObserver(
      (entries) => {
        visible = entries.some((e) => e.isIntersecting);
        if (visible) kick();
        else if (raf) {
          cancelAnimationFrame(raf);
          raf = 0;
        }
      },
      { rootMargin: "80px" },
    );
    io.observe(container);

    const onVisibility = () => {
      if (document.visibilityState === "visible") kick();
    };
    document.addEventListener("visibilitychange", onVisibility);

    // Rebuild the atlas once the webfont is actually available to canvas.
    let alive = true;
    document.fonts?.ready.then(() => {
      if (!alive) return;
      atlasKey = "";
      relayout();
    });

    const target = o.pointerTarget?.current ?? null;
    const onMove = (e: PointerEvent) => {
      if (e.pointerType !== "mouse" || !fineMq.matches) return;
      const r = canvas.getBoundingClientRect();
      ptX = e.clientX - r.left;
      ptY = e.clientY - r.top;
      if (pOn < 0.01) {
        pX = ptX;
        pY = ptY;
      }
      ptOn = 1;
    };
    const onLeave = () => {
      ptOn = 0;
    };
    if (target && !reducedMotion) {
      target.addEventListener("pointermove", onMove, { passive: true });
      target.addEventListener("pointerleave", onLeave, { passive: true });
    }

    return () => {
      alive = false;
      if (raf) cancelAnimationFrame(raf);
      ro.disconnect();
      io.disconnect();
      document.removeEventListener("visibilitychange", onVisibility);
      if (target) {
        target.removeEventListener("pointermove", onMove);
        target.removeEventListener("pointerleave", onLeave);
      }
    };
  }, [reducedMotion]);

  return { containerRef, canvasRef };
}
