"use client";

import type { RefObject } from "react";
import type { MotionValue } from "motion/react";
import { useAsciiCanvas } from "./useAsciiCanvas";
import type { AsciiField } from "./types";

export interface AsciiCanvasProps {
  field: AsciiField;
  reducedMotion: boolean;
  progress?: MotionValue<number>;
  pointerTarget?: RefObject<HTMLElement | null>;
  cellSize?: number;
  compactCellSize?: number;
  introSeconds?: number;
  staticProgress?: number;
  pointerRadius?: number;
  className?: string;
}

/** A sized box holding one ASCII canvas. The parent decides the box; the canvas fills it. */
export function AsciiCanvas({ className, ...options }: AsciiCanvasProps) {
  const { containerRef, canvasRef } = useAsciiCanvas(options);
  return (
    <div ref={containerRef} className={className} aria-hidden="true">
      <canvas ref={canvasRef} className="block h-full w-full" />
    </div>
  );
}
