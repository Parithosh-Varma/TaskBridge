"use client";

import { useScroll } from "motion/react";
import { useRef } from "react";
import { AsciiCanvas } from "@/components/ascii/AsciiCanvas";
import { calmField } from "@/components/ascii/fields";
import { CommandBlock } from "@/components/ui/CommandBlock";
import { Reveal } from "@/components/ui/Reveal";
import { StarButton } from "@/components/ui/StarButton";
import { usePrefersReducedMotion } from "@/lib/usePrefersReducedMotion";

export function FinalCta({ stars }: { stars: number }) {
  const ref = useRef<HTMLElement>(null);
  const reduced = usePrefersReducedMotion();
  const { scrollYProgress } = useScroll({ target: ref, offset: ["start end", "center center"] });

  return (
    <section ref={ref} aria-labelledby="cta-title" className="relative isolate overflow-hidden border-t border-line">
      <AsciiCanvas
        field={calmField}
        progress={scrollYProgress}
        reducedMotion={reduced}
        staticProgress={1}
        className="absolute inset-0 -z-10 opacity-80"
      />
      <Reveal className="mx-auto flex max-w-3xl flex-col items-center px-5 py-28 text-center sm:px-8 md:py-40">
        <span aria-hidden="true" className="font-mono text-[28px] text-signal glow-signal">
          ◆
        </span>
        <h2
          id="cta-title"
          className="mt-6 font-mono text-[32px] leading-[1.08] font-extrabold tracking-[-0.04em] text-paper sm:text-[48px]"
        >
          Fork it. Self-host it.
          <br />
          Build on it.
        </h2>
        <p className="mt-5 font-mono text-[12px] uppercase tracking-[0.22em] text-faint">Apache-2.0</p>
        <div className="mt-9 flex flex-col items-center gap-5">
          <StarButton stars={stars} />
          <CommandBlock
            command="git clone https://github.com/Parithosh-Varma/TaskBridge.git"
            className="w-full max-w-[36rem] bg-bg/90 text-left"
          />
        </div>
      </Reveal>
    </section>
  );
}
