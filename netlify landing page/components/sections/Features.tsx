"use client";

import { motion } from "motion/react";
import { SectionHead } from "@/components/ui/SectionHead";
import { EASE_OUT } from "@/components/ui/Reveal";
import { FEATURES } from "@/lib/content";
import { usePrefersReducedMotion } from "@/lib/usePrefersReducedMotion";

export function Features() {
  const reduced = usePrefersReducedMotion();

  return (
    <section id="features" aria-labelledby="features-title" className="border-t border-line">
      <div className="mx-auto max-w-6xl px-5 py-24 sm:px-8 md:py-32">
        <SectionHead
          id="features-title"
          index="03"
          kicker="The spec sheet"
          title="What ships in the box."
          lede="Ten line items from the README. Tool names are the real ones."
        />

        <motion.ul
          key={reduced ? "static" : "animated"}
          className="mt-14 border-t border-line"
          initial={reduced ? false : "hidden"}
          whileInView="shown"
          viewport={{ once: true, margin: "0px 0px -12% 0px" }}
          variants={{ shown: { transition: { staggerChildren: 0.04 } } }}
        >
          {FEATURES.map((f, i) => (
            <motion.li
              key={f.title}
              variants={{
                hidden: { opacity: 0, y: 14 },
                shown: { opacity: 1, y: 0, transition: { duration: 0.5, ease: EASE_OUT } },
              }}
              className="group grid grid-cols-[2.75rem_1fr] gap-x-4 gap-y-3 border-b border-line py-6 transition-colors duration-300 hover:bg-panel/60 md:grid-cols-[3.5rem_15rem_1fr_auto] md:items-baseline md:gap-x-6 md:px-3"
            >
              <span
                aria-hidden="true"
                className="flex h-9 w-9 items-center justify-center self-start rounded-[3px] border border-line bg-panel font-mono text-[16px] text-signal transition-colors group-hover:border-signal/50 md:h-10 md:w-10"
              >
                <span className="cell">{f.glyph}</span>
              </span>
              <h3 className="self-center font-mono text-[15px] font-semibold tracking-[-0.01em] text-paper md:self-baseline">
                <span className="mr-2 text-[11px] font-normal text-faint tabular-nums">{String(i + 1).padStart(2, "0")}</span>
                {f.title}
              </h3>
              <p className="col-span-2 text-[15px] leading-[1.6] text-paper/75 md:col-span-1">{f.body}</p>
              {f.tools ? (
                <div className="col-span-2 flex flex-wrap gap-1.5 md:col-span-1 md:max-w-[17rem] md:justify-end">
                  {f.tools.map((t) => (
                    <code key={t} className="chip">
                      {t}
                    </code>
                  ))}
                </div>
              ) : null}
            </motion.li>
          ))}
        </motion.ul>
      </div>
    </section>
  );
}
