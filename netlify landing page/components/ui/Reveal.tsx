"use client";

import { motion } from "motion/react";
import type { ReactNode } from "react";
import { usePrefersReducedMotion } from "@/lib/usePrefersReducedMotion";

export const EASE_OUT = [0.16, 1, 0.3, 1] as const;

interface RevealProps {
  children: ReactNode;
  className?: string;
  delay?: number;
  as?: "div" | "li" | "section";
}

/** Fade + 14px rise, once, when scrolled into view. Static under reduced motion. */
export function Reveal({ children, className, delay = 0, as = "div" }: RevealProps) {
  const reduced = usePrefersReducedMotion();
  if (reduced) {
    const Tag = as;
    return <Tag className={className}>{children}</Tag>;
  }
  const motionProps = {
    className,
    initial: { opacity: 0, y: 14 },
    whileInView: { opacity: 1, y: 0 },
    viewport: { once: true, margin: "0px 0px -10% 0px" },
    transition: { duration: 0.55, ease: EASE_OUT, delay },
  } as const;
  if (as === "li") return <motion.li {...motionProps}>{children}</motion.li>;
  if (as === "section") return <motion.section {...motionProps}>{children}</motion.section>;
  return <motion.div {...motionProps}>{children}</motion.div>;
}
