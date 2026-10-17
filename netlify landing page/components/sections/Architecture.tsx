"use client";

import { motion, useMotionValueEvent, useScroll, useTransform } from "motion/react";
import { useRef, useState } from "react";
import { AsciiScene } from "@/components/ascii/AsciiScene";
import { DIAGRAM_STAGES, DIAGRAM_STROKES } from "@/lib/diagram";
import { usePrefersReducedMotion } from "@/lib/usePrefersReducedMotion";

const STAGES = DIAGRAM_STAGES.length;
// Section progress → diagram progress: draw over the first 78%, hold, then recede.
const DRAW_END = 0.78;

export function Architecture() {
  const ref = useRef<HTMLElement>(null);
  const reduced = usePrefersReducedMotion();
  const { scrollYProgress } = useScroll({ target: ref, offset: ["start start", "end end"] });
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
      className={`relative border-t border-line ${reduced ? "" : "h-[320vh]"}`}
    >
      <div className={reduced ? "" : "sticky top-14 flex h-[calc(100svh-3.5rem)] flex-col justify-center overflow-hidden"}>
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

          <motion.div
            style={reduced ? undefined : { opacity, scale }}
            className="term-card mt-8 overflow-x-auto bg-panel/60 px-4 py-6 sm:px-8"
          >
            <AsciiScene
              strokes={DIAGRAM_STROKES}
              stages={STAGES}
              progress={draw}
              complete={reduced}
              label="Architecture: Claude submits a task over MCP to opencode_bridge_mcp.py, which writes it to the SQLite queue tasks.db. worker.py claims it within about 60 seconds, by priority and oldest first, and runs opencode run in a git worktree. The structured result — summary, files touched, tests run, open questions — plus a diff returns to Claude through get_task_result. In reverse, OpenCode can call Claude with claude_ask."
              className="mx-auto w-max font-mono text-[clamp(7px,min(1.62vw,1.8vh),14.5px)] leading-[1.6] text-paper"
            />
          </motion.div>

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
                <span className="text-signal">▸ {DIAGRAM_STAGES[shownStage].title.toLowerCase()}</span>
                <span className="mx-2 text-line">—</span>
                {DIAGRAM_STAGES[shownStage].caption}
              </motion.p>
            )}
          </div>
        </div>
      </div>
    </section>
  );
}
