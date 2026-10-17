"use client";

import { motion, useScroll, useTransform } from "motion/react";
import { useRef } from "react";
import { AsciiCanvas } from "@/components/ascii/AsciiCanvas";
import { heroField } from "@/components/ascii/fields";
import { CommandBlock } from "@/components/ui/CommandBlock";
import { StarButton } from "@/components/ui/StarButton";
import { INSTALL_ONE_LINER } from "@/lib/content";
import { usePrefersReducedMotion } from "@/lib/usePrefersReducedMotion";

export function Hero({ stars }: { stars: number }) {
  const sectionRef = useRef<HTMLElement>(null);
  const reduced = usePrefersReducedMotion();
  const { scrollYProgress } = useScroll({ target: sectionRef, offset: ["start start", "end start"] });
  const { scrollY } = useScroll();
  const hintOpacity = useTransform(scrollY, [0, 120], [1, 0]);

  return (
    <section
      ref={sectionRef}
      id="top"
      aria-labelledby="hero-title"
      className="relative isolate flex min-h-[calc(100svh-3.5rem)] flex-col overflow-hidden"
    >
      {/* Scrims: keep type legible over the field, plus a soft vignette. */}
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-0 -z-10 hidden md:block md:bg-[linear-gradient(90deg,var(--bg)_0%,rgba(16,12,8,0.94)_30%,rgba(16,12,8,0.55)_46%,transparent_62%)]"
      />
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-0 -z-10 bg-[radial-gradient(ellipse_at_60%_50%,transparent_40%,rgba(16,12,8,0.75)_100%)]"
      />

      <div className="mx-auto flex w-full max-w-6xl flex-1 flex-col justify-start px-5 pt-10 pb-4 sm:px-8 md:justify-center md:pt-16 md:pb-24">
        <div className="max-w-[34rem]">
          <p className="hero-in eyebrow" style={{ animationDelay: "0.05s" }}>
            MCP task bridge <span className="mx-1.5 text-line">·</span> SQLite queue
            <span className="mx-1.5 text-line">·</span> Apache-2.0
          </p>
          <h1
            id="hero-title"
            className="hero-in mt-5 font-mono text-[40px] leading-[1.02] font-extrabold tracking-[-0.045em] text-paper sm:text-[56px] lg:text-[64px]"
            style={{ animationDelay: "0.12s" }}
          >
            Claude plans.
            <br />
            <span className="ramp-text">OpenCode builds.</span>
          </h1>
          <p className="hero-in mt-5 max-w-[30rem] text-[16px] leading-[1.6] text-paper/80 sm:text-[17px]" style={{ animationDelay: "0.22s" }}>
            Dispatch real coding work from Claude to headless OpenCode agents via a durable SQLite queue. Structured
            results, git-aware diffs, receipts.
          </p>
          <div className="hero-in mt-7" style={{ animationDelay: "0.32s" }}>
            <CommandBlock command={INSTALL_ONE_LINER} className="bg-panel/90 backdrop-blur-sm" />
          </div>
          <div className="hero-in mt-5 flex flex-wrap items-center gap-3" style={{ animationDelay: "0.4s" }}>
            <StarButton stars={stars} />
            <a
              href="#quickstart"
              className="inline-flex items-center gap-2 rounded-[4px] px-4 py-3 font-mono text-[13px] text-paper/85 transition-colors duration-200 hover:bg-panel hover:text-paper"
            >
              Read the docs <span aria-hidden="true">→</span>
            </a>
          </div>
        </div>
      </div>

      {/* The pipeline: full-bleed behind the copy on desktop, a band under it on phones. */}
      <AsciiCanvas
        field={heroField}
        progress={scrollYProgress}
        pointerTarget={sectionRef}
        reducedMotion={reduced}
        introSeconds={2.4}
        staticProgress={0.7}
        className="relative -z-20 h-[230px] w-full [mask-image:linear-gradient(180deg,transparent,#000_28%)] md:absolute md:inset-0 md:h-auto md:[mask-image:none]"
      />

      <motion.a
        href="#why"
        style={reduced ? undefined : { opacity: hintOpacity }}
        className="absolute bottom-5 left-1/2 hidden -translate-x-1/2 font-mono text-[11px] uppercase tracking-[0.22em] text-faint md:block"
      >
        <span className={reduced ? "" : "animate-pulse-soft inline-block"}>▼ scroll</span>
      </motion.a>
    </section>
  );
}
