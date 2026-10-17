"use client";

import { motion, useInView } from "motion/react";
import { useEffect, useRef, useState } from "react";
import { AsciiCanvas } from "@/components/ascii/AsciiCanvas";
import { engineField } from "@/components/ascii/fields";
import { BOARD_FEED, type TermTone } from "@/lib/content";

const TALLY = [
  { label: "pending", value: 3, tone: "text-paper" },
  { label: "running", value: 1, tone: "text-signal" },
  { label: "waiting", value: 1, tone: "text-wait" },
  { label: "done", value: 12, tone: "text-seal" },
] as const;

const TONE: Record<TermTone, string> = {
  cmd: "text-paper",
  out: "text-paper/80",
  faint: "text-faint",
  wait: "text-wait",
  seal: "text-seal",
  signal: "text-signal",
  ember: "text-ember",
};

const VISIBLE = 6;
const BASE_SECONDS = 5 * 3600 + 49 * 60 + 12;

function clock(seq: number) {
  const s = BASE_SECONDS + seq * 4 + ((seq * 7) % 3);
  const hh = String(Math.floor(s / 3600) % 24).padStart(2, "0");
  const mm = String(Math.floor(s / 60) % 60).padStart(2, "0");
  const ss = String(s % 60).padStart(2, "0");
  return `${hh}:${mm}:${ss}`;
}

function Tally({ value, run, reduced }: { value: number; run: boolean; reduced: boolean }) {
  const [shown, setShown] = useState<string>(() => String(value).padStart(2, "0"));
  useEffect(() => {
    if (!run || reduced) return;
    const start = performance.now();
    let id = 0;
    const tick = () => {
      const t = performance.now() - start;
      if (t > 950) {
        setShown(String(value).padStart(2, "0"));
        return;
      }
      setShown(String(Math.floor(Math.random() * 100)).padStart(2, "0"));
      id = window.setTimeout(tick, 55);
    };
    id = window.setTimeout(tick, 0);
    return () => window.clearTimeout(id);
  }, [run, reduced, value]);
  return <>{shown}</>;
}

export function DispatchBoard({ reduced }: { reduced: boolean }) {
  const ref = useRef<HTMLDivElement>(null);
  const seen = useInView(ref, { once: true, amount: 0.4 });
  const inView = useInView(ref, { amount: 0.1 });
  const [seq, setSeq] = useState(VISIBLE);

  useEffect(() => {
    if (reduced || !inView) return;
    const id = window.setInterval(() => setSeq((s) => s + 1), 1700);
    return () => window.clearInterval(id);
  }, [reduced, inView]);

  const feed = Array.from({ length: VISIBLE }, (_, k) => {
    const n = seq - VISIBLE + k;
    return { n, ...BOARD_FEED[n % BOARD_FEED.length] };
  });

  return (
    <div ref={ref} className="term-card flex h-full flex-col overflow-hidden font-mono">
      <div className="flex items-center justify-between border-b border-line px-4 py-2.5">
        <p className="eyebrow text-[10px]">┌ dispatch board</p>
        <p className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-[0.2em] text-signal">
          <span aria-hidden="true" className={reduced ? "" : "animate-lamp"}>
            ●
          </span>
          worker online
        </p>
      </div>

      <dl className="grid grid-cols-4 border-b border-line">
        {TALLY.map((t) => (
          <div key={t.label} className="border-r border-line px-3 py-4 last:border-r-0 sm:px-4">
            <dt className="text-[10px] uppercase tracking-[0.18em] text-faint">{t.label}</dt>
            <dd className={`mt-1 text-[26px] leading-none font-bold tabular-nums tracking-[-0.03em] sm:text-[30px] ${t.tone}`}>
              <Tally value={t.value} run={seen} reduced={reduced} />
            </dd>
          </div>
        ))}
      </dl>

      <div className="border-b border-line">
        <p className="eyebrow px-4 pt-3 text-[10px]">engine tail</p>
        <AsciiCanvas
          field={engineField}
          reducedMotion={reduced}
          pointerTarget={ref}
          cellSize={12}
          compactCellSize={10}
          pointerRadius={110}
          className="h-[78px] w-full"
        />
      </div>

      <div className="flex-1 px-4 py-3">
        <p className="eyebrow mb-2 text-[10px]">fresh output</p>
        <ol className="space-y-1 text-[12px] leading-[1.6]" aria-label="Example log feed">
          {feed.map((l) => (
            <motion.li
              key={l.n}
              initial={reduced ? false : { opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.4, ease: [0.16, 1, 0.3, 1] }}
              className="flex gap-3 whitespace-nowrap"
            >
              <span className="text-line tabular-nums">{clock(l.n)}</span>
              <span className="text-faint">{l.id}</span>
              <span className={`truncate ${TONE[l.tone]}`}>{l.text}</span>
            </motion.li>
          ))}
        </ol>
      </div>
    </div>
  );
}
