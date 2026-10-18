"use client";

import { useId, useState } from "react";
import { AsciiTexture } from "@/components/ascii/AsciiTexture";
import { AsciiRule } from "@/components/ui/AsciiRule";
import { SectionHead } from "@/components/ui/SectionHead";
import { Reveal } from "@/components/ui/Reveal";
import { FAQ } from "@/lib/content";

export function Faq() {
  const [open, setOpen] = useState<number | null>(0);
  const base = useId();

  return (
    <section id="faq" aria-labelledby="faq-title" className="relative isolate">
      <AsciiRule />
      <AsciiTexture variant="grid" />
      <div className="mx-auto grid max-w-6xl gap-12 px-5 py-24 sm:px-8 md:grid-cols-[1fr_1.6fr] md:gap-16 md:py-32">
        <SectionHead
          id="faq-title"
          index="07"
          kicker="Troubleshooting"
          title="When the line goes quiet."
          lede="Straight from the README's troubleshooting notes."
          className="md:sticky md:top-24 md:self-start"
        />

        <Reveal>
          <AsciiRule />
          <ul>
            {FAQ.map((item, i) => {
              const isOpen = open === i;
              const btnId = `${base}-q${i}`;
              const panelId = `${base}-a${i}`;
              return (
                <li key={item.q} className="sep-b">
                  <h3>
                    <button
                      id={btnId}
                      type="button"
                      aria-expanded={isOpen}
                      aria-controls={panelId}
                      onClick={() => setOpen(isOpen ? null : i)}
                      className="group flex w-full items-center justify-between gap-6 py-5 text-left font-mono text-[15px] font-medium tracking-[-0.01em] text-paper transition-colors hover:text-signal"
                    >
                      <span>
                        <span className="mr-3 text-[11px] text-faint tabular-nums">{String(i + 1).padStart(2, "0")}</span>
                        {item.q}
                      </span>
                      <span
                        aria-hidden="true"
                        className={`shrink-0 font-mono text-[13px] transition-colors duration-200 group-hover:text-signal ${
                          isOpen ? "text-signal" : "text-faint"
                        }`}
                      >
                        {isOpen ? "[-]" : "[+]"}
                      </span>
                    </button>
                  </h3>
                  <div
                    id={panelId}
                    role="region"
                    aria-labelledby={btnId}
                    inert={!isOpen}
                    className={`grid transition-[grid-template-rows,opacity] duration-400 ease-[var(--ease-out)] ${isOpen ? "grid-rows-[1fr] opacity-100" : "grid-rows-[0fr] opacity-0"}`}
                  >
                    <div className="overflow-hidden">
                      <p className="max-w-[40rem] pr-8 pb-6 pl-8 text-[15px] leading-[1.65] text-paper/75">{item.a}</p>
                    </div>
                  </div>
                </li>
              );
            })}
          </ul>
        </Reveal>
      </div>
    </section>
  );
}
