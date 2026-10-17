"use client";

import { useMemo, useState } from "react";
import { useMotionValueEvent, type MotionValue } from "motion/react";

export type SceneTone = "paper" | "faint" | "line" | "ember" | "signal" | "seal" | "wait";

/** A run of text placed on the grid. Strokes in a stage draw in order, character by character. */
export interface SceneStroke {
  row: number;
  col: number;
  text: string;
  tone: SceneTone;
  stage: number;
}

export interface AsciiSceneProps {
  strokes: SceneStroke[];
  stages: number;
  /** 0..1 reveal progress. Stage s occupies [s/stages, (s+1)/stages]. */
  progress: MotionValue<number>;
  /** Draw everything, no animation. */
  complete?: boolean;
  className?: string;
  label: string;
}

interface Cell {
  ch: string;
  tone: SceneTone;
  stage: number;
  /** Progress at which this cell appears. */
  at: number;
}

// Glyphs outside JetBrains Mono's coverage would break column alignment; pin them to 1ch.
const WIDE_RISK = /[⛁▣▤⟲⚑⊞◆●★]/;

const TONE_CLASS: Record<SceneTone, string> = {
  paper: "text-paper",
  faint: "text-faint",
  line: "text-[#6b5a43]",
  ember: "text-ember",
  signal: "text-signal",
  seal: "text-seal",
  wait: "text-wait",
};

const STEPS = 480;

function buildGrid(strokes: SceneStroke[], stages: number) {
  const width = Math.max(...strokes.map((s) => s.col + [...s.text].length));
  const height = Math.max(...strokes.map((s) => s.row)) + 1;
  const grid: (Cell | null)[][] = Array.from({ length: height }, () => Array<Cell | null>(width).fill(null));

  for (let stage = 0; stage < stages; stage++) {
    const inStage = strokes.filter((s) => s.stage === stage);
    const total = inStage.reduce((n, s) => n + [...s.text].filter((c) => c !== " ").length, 0) || 1;
    let drawn = 0;
    for (const s of inStage) {
      [...s.text].forEach((ch, k) => {
        if (ch === " ") return;
        const at = (stage + (drawn / total) * 0.82) / stages;
        drawn++;
        grid[s.row][s.col + k] = { ch, tone: s.tone, stage, at };
      });
    }
  }
  return grid;
}

/** Line-art on a fixed monospace grid that draws itself as `progress` advances. */
export function AsciiScene({ strokes, stages, progress, complete = false, className, label }: AsciiSceneProps) {
  const grid = useMemo(() => buildGrid(strokes, stages), [strokes, stages]);
  const [step, setStep] = useState(() => Math.round(progress.get() * STEPS));

  useMotionValueEvent(progress, "change", (v) => {
    const next = Math.round(Math.min(1, Math.max(0, v)) * STEPS);
    setStep((prev) => (prev === next ? prev : next));
  });

  const p = complete ? 1 : step / STEPS;
  const active = complete ? stages : Math.min(stages - 1, Math.floor(p * stages));
  // The most recently drawn cell gets the cursor highlight.
  let headAt = -1;
  if (!complete) {
    for (const row of grid) for (const c of row) if (c && c.at <= p && c.at > headAt) headAt = c.at;
  }

  return (
    <pre role="img" aria-label={label} className={className}>
      {grid.map((row, r) => (
        <span key={r} className="block">
          {row.map((c, k) => {
            if (!c) return " ";
            const shown = c.at <= p;
            const isHead = shown && c.at === headAt;
            const dim = !complete && c.stage < active;
            const cls = [
              WIDE_RISK.test(c.ch) ? "cell" : "",
              isHead ? "text-signal glow-signal" : TONE_CLASS[c.tone],
              shown ? (dim ? "opacity-60" : "opacity-100") : "opacity-0",
              "transition-opacity duration-300",
            ].join(" ");
            return (
              <span key={k} className={cls}>
                {c.ch}
              </span>
            );
          })}
        </span>
      ))}
    </pre>
  );
}
