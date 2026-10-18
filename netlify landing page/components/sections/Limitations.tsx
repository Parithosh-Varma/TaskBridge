import { AsciiTexture } from "@/components/ascii/AsciiTexture";
import { AsciiRule } from "@/components/ui/AsciiRule";
import { Reveal } from "@/components/ui/Reveal";
import { LIMITATIONS } from "@/lib/content";

export function Limitations() {
  return (
    <section id="limitations" aria-labelledby="limits-title" className="relative isolate">
      <AsciiRule />
      <AsciiTexture variant="margin" />
      <div className="mx-auto max-w-6xl px-5 py-24 sm:px-8 md:py-28">
        <Reveal className="ascii-corners border border-dashed border-faint/40 p-6 sm:p-10">
          <p className="eyebrow">
            <span className="text-signal">07</span>
            <span className="mx-2 text-line">/</span>
            Receipts
          </p>
          <h2
            id="limits-title"
            className="mt-4 font-mono text-[28px] leading-[1.12] font-bold tracking-[-0.03em] text-paper sm:text-[36px]"
          >
            What it won&apos;t do
          </h2>
          <p className="mt-3 text-[16px] text-paper/75">Every bridge has a load limit. Here&apos;s ours, up front.</p>

          <ul className="mt-10 grid gap-px overflow-hidden border border-line bg-line sm:grid-cols-2">
            {LIMITATIONS.map((l, i) => (
              <li key={l.title} className="bg-bg p-6">
                <p className="font-mono text-[12px] uppercase tracking-[0.16em] text-faint">
                  <span className="text-ember">x</span> {String(i + 1).padStart(2, "0")}
                </p>
                <h3 className="mt-3 font-mono text-[16px] font-semibold text-paper">{l.title}</h3>
                <p className="mt-2 text-[15px] leading-[1.6] text-paper/75">{l.body}</p>
              </li>
            ))}
          </ul>
        </Reveal>
      </div>
    </section>
  );
}
