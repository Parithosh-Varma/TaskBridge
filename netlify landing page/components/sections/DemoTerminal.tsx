"use client";

import { useMotionValueEvent, type MotionValue } from "motion/react";
import { useMemo, useState } from "react";
import { TERMINAL_SCRIPT, type TermTone } from "@/lib/content";

const TONE: Record<TermTone, string> = {
  cmd: "text-paper",
  out: "text-paper/80",
  faint: "text-faint",
  wait: "text-wait",
  seal: "text-seal",
  signal: "text-signal",
  ember: "text-ember",
};

/** Printed output costs this many "characters" of scroll, so it lands with a beat. */
const OUTPUT_WEIGHT = 16;
const STEPS = 600;

export function DemoTerminal({ progress, complete }: { progress: MotionValue<number>; complete: boolean }) {
  const { spans, total } = useMemo(() => {
    let at = 0;
    const spans = TERMINAL_SCRIPT.map((l) => {
      const w = l.typed ? l.text.length : OUTPUT_WEIGHT;
      const s = { start: at, end: at + w };
      at += w;
      return s;
    });
    return { spans, total: at };
  }, []);

  const [step, setStep] = useState(() => Math.round(progress.get() * STEPS));
  useMotionValueEvent(progress, "change", (v) => {
    const next = Math.round(Math.min(1, Math.max(0, v)) * STEPS);
    setStep((prev) => (prev === next ? prev : next));
  });

  const units = complete ? total : (step / STEPS) * total;
  const activeIndex = complete ? -1 : spans.findIndex((s) => units < s.end);

  return (
    <div className="term-card flex h-full flex-col overflow-hidden bg-[#140f0a]">
      <div className="flex items-center justify-between border-b border-line px-4 py-2.5">
        <div className="flex items-center gap-1.5" aria-hidden="true">
          <span className="h-2 w-2 rounded-full bg-line" />
          <span className="h-2 w-2 rounded-full bg-line" />
          <span className="h-2 w-2 rounded-full bg-line" />
        </div>
        <p className="eyebrow text-[10px]">claude · taskbridge mcp · illustrative session</p>
      </div>
      <div className="overflow-x-auto px-4 py-4">
        <pre
          role="img"
          aria-label="Illustrative session: Claude submits a task, the worker pauses with a question, Claude answers with answer_task, the run resumes, and get_task_result returns a summary, files touched, tests run, and a diff."
          className="w-max font-mono text-[11.5px] leading-[1.7] sm:text-[12.5px]"
        >
          {TERMINAL_SCRIPT.map((l, i) => {
            const s = spans[i];
            const isCmdStart = l.typed && !l.text.startsWith(" ");
            const prompt = isCmdStart ? "› " : "  ";
            let shown: number;
            if (units >= s.end) shown = l.text.length;
            else if (units < s.start) shown = 0;
            else shown = l.typed ? Math.floor(units - s.start) : 0;
            const visible = shown > 0;
            return (
              <span key={i} className={`block ${TONE[l.tone]}`}>
                <span className={`select-none ${isCmdStart ? "text-signal" : ""} ${visible ? "" : "opacity-0"}`}>
                  {prompt}
                </span>
                {l.text.slice(0, shown)}
                {i === activeIndex && l.typed ? (
                  <span aria-hidden="true" className="animate-caret -ml-px inline-block w-[0.6em] bg-signal/80 text-transparent">
                    _
                  </span>
                ) : null}
                <span className="opacity-0" aria-hidden="true">
                  {l.text.slice(shown)}
                </span>
              </span>
            );
          })}
        </pre>
      </div>
    </div>
  );
}
