"use client";

import { MotionConfig } from "motion/react";
import type { ReactNode } from "react";

/** Motion honours the OS reduced-motion setting everywhere, as a backstop to per-component checks. */
export function Providers({ children }: { children: ReactNode }) {
  return <MotionConfig reducedMotion="user">{children}</MotionConfig>;
}
