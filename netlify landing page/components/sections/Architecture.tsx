"use client";

import { motion, useMotionValueEvent, useScroll, useTransform } from "motion/react";
import { useRef, useState } from "react";
import { AsciiTexture } from "@/components/ascii/AsciiTexture";
import { MermaidGraph } from "@/components/diagram/MermaidGraph";
import { AsciiRule } from "@/components/ui/AsciiRule";
import { DIAGRAM_STAGES } from "@/lib/diagram";
import { usePrefersReducedMotion } from "@/lib/usePrefersReducedMotion";

const STAGES = DIAGRAM_STAGES.length;
// Section progress → diagram progress: draw over the first 78%, hold, then recede.
const DRAW_END = 0.78;

export function Architecture() {
  const ref = useRef<HTMLElement>(null);
  const reduced = usePrefersReducedMotion();
  // From the section entering the viewport to its end: the card has already started drawing by the
  // time it is fully on screen, so it never greets the reader as an empty box.
  const { scrollYProgress } = useScroll({ target: ref, offset: ["start end", "end end"] });
  const draw = useTransform(scrollYProgress, [0.02, DRAW_END], [0, 1], { clamp: true });
  const opacity = useTransform(scrollYProgress, [0.9, 1], [1, 0.35]);
  const scale = useTransform(scrollYProgress, [0.9, 1], [1, 0.975]);
  const [stage, setStage] = useState(0);

  useMotionValueEvent(draw, "change", (v) => {
    const s = Math.min(STAGES - 1, Math.floor(v * STAGES));
    setStage((prev) => (prev === s ? prev : s));
  });

  const shownStage = reduced ? null : stage;

  return (
    <section
      ref={ref}
      id="architecture"
      aria-labelledby="arch-title"
      className={`relative isolate ${reduced ? "" : "h-[320vh]"}`}
    >
      <AsciiRule />
      <div
        className={`relative ${reduced ? "" : "sticky top-14 flex h-[calc(100svh-3.5rem)] flex-col justify-center overflow-hidden"}`}
      >
        <AsciiTexture variant="grid" className="opacity-60" />
        <div className="mx-auto w-full max-w-6xl px-5 py-8 sm:px-8">
          <div className="flex flex-wrap items-end justify-between gap-6">
            <div className="max-w-xl">
              <p className="eyebrow">
                <span className="text-signal">02</span>
                <span className="mx-2 text-line">/</span>
                The scrolling diagram
              </p>
              <h2
                id="arch-title"
                className="mt-4 font-mono text-[28px] leading-[1.12] font-bold tracking-[-0.03em] text-paper sm:text-[36px]"
              >
                One task, end to end.
              </h2>
            </div>
            {!reduced && (
              <ol className="hidden flex-wrap gap-x-4 md:flex gap-y-1 font-mono text-[11px] uppercase tracking-[0.18em]" aria-hidden="true">
                {DIAGRAM_STAGES.map((s, i) => (
                  <li key={s.title} className={`transition-colors duration-300 ${i === stage ? "text-signal" : i < stage ? "text-paper/60" : "text-line"}`}>
                    {String(i + 1).padStart(2, "0")} {s.title}
                  </li>
                ))}
              </ol>
            )}
          </div>

          <div className="relative mt-8">
            <motion.div
              style={reduced ? undefined : { opacity, scale }}
              className="term-card overflow-x-auto bg-panel/60 px-3 py-5 sm:px-8"
            >
              <MermaidGraph
                progress={draw}
                complete={reduced}
                label="Architecture: Claude submits a task over MCP to opencode_bridge_mcp.py, which writes it to the SQLite queue tasks.db. worker.py claims it within about 60 seconds, by priority and oldest first, and runs opencode run in a git worktree. The structured result — summary, files touched, tests run, open questions — plus a diff returns to Claude through get_task_result. In reverse, OpenCode can call Claude with claude_ask."
                className="mx-auto min-w-[820px] max-w-[1120px] sm:min-w-0"
              />
            </motion.div>
            {/* Phones: the graph is wider than the card and scrolls sideways; fade the cut edge. */}
            <span
              aria-hidden="true"
              className="pointer-events-none absolute inset-y-px right-px w-10 bg-gradient-to-l from-bg to-transparent sm:hidden"
            />
          </div>

          {/* A diagram this wide can only be read a column at a time on a phone: say how. */}
          <p className="mt-2.5 font-mono text-[10px] tracking-[0.2em] text-line uppercase sm:hidden">
            <span className={reduced ? "" : "animate-pulse-soft inline-block"}>pan the diagram --&gt;</span>
          </p>

          <div className="mt-6 min-h-[3.5rem] font-mono text-[13px] leading-6 text-faint" aria-live="off">
            {shownStage === null ? (
              <ol className="grid gap-2 sm:grid-cols-2">
                {DIAGRAM_STAGES.map((s, i) => (
                  <li key={s.title}>
                    <span className="text-signal">{String(i + 1).padStart(2, "0")}</span> {s.caption}
                  </li>
                ))}
              </ol>
            ) : (
              <motion.p key={shownStage} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.35 }}>
                <span className="text-signal">&gt; {DIAGRAM_STAGES[shownStage].title.toLowerCase()}</span>
                <span className="mx-2 text-line">--</span>
                {DIAGRAM_STAGES[shownStage].caption}
              </motion.p>
            )}
          </div>
        </div>
      </div>
    </section>
  );
}
