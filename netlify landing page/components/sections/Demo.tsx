"use client";

import { useScroll, useTransform } from "motion/react";
import { useRef } from "react";
import { SectionHead } from "@/components/ui/SectionHead";
import { DemoTerminal } from "./DemoTerminal";
import { DispatchBoard } from "./DispatchBoard";
import { usePrefersReducedMotion } from "@/lib/usePrefersReducedMotion";

export function Demo() {
  const ref = useRef<HTMLElement>(null);
  const reduced = usePrefersReducedMotion();
  const { scrollYProgress } = useScroll({ target: ref, offset: ["start 0.7", "end 0.85"] });
  const typing = useTransform(scrollYProgress, [0.05, 0.8], [0, 1], { clamp: true });

  return (
    <section ref={ref} id="demo" aria-labelledby="demo-title" className="border-t border-line">
      <div className="mx-auto max-w-6xl px-5 py-24 sm:px-8 md:py-32">
        <SectionHead
          id="demo-title"
          index="05"
          kicker="Demo"
          title="A task with a question in the middle."
          lede="Scroll to run it. The worker pauses, Claude answers, the run resumes, and the receipt comes back."
        />

        <div className="mt-14 grid gap-6 lg:grid-cols-[1.12fr_1fr]">
          <DemoTerminal progress={typing} complete={reduced} />
          <div className="flex flex-col">
            <DispatchBoard reduced={reduced} />
            <p className="mt-4 font-mono text-[12px] leading-[1.6] text-faint">
              a stylized view of a real one — the actual board ships at <code className="text-paper/85">GET /</code> on the same
              host.
            </p>
          </div>
        </div>
      </div>
    </section>
  );
}
