"use client";

import { usePrefersReducedMotion } from "@/lib/usePrefersReducedMotion";
import { AsciiCanvas } from "./AsciiCanvas";
import { gridField, marginField } from "./fields";

export interface AsciiTextureProps {
  /** `grid` is graph-paper dots; `margin` keeps grain to the edges and the centre quiet. */
  variant?: "grid" | "margin";
  className?: string;
}

/**
 * A quiet ASCII field behind a section's content. Decorative by construction: no
 * pointer effect, paused off-screen, a single static frame under reduced motion.
 */
export function AsciiTexture({ variant = "grid", className = "" }: AsciiTextureProps) {
  const reduced = usePrefersReducedMotion();
  return (
    <AsciiCanvas
      field={variant === "margin" ? marginField : gridField}
      reducedMotion={reduced}
      cellSize={18}
      compactCellSize={16}
      staticProgress={0.5}
      className={`pointer-events-none absolute inset-0 -z-10 ${className}`}
    />
  );
}
