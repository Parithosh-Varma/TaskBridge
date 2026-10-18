import { AsciiRule } from "@/components/ui/AsciiRule";
import { Reveal } from "@/components/ui/Reveal";
import { SectionHead } from "@/components/ui/SectionHead";

const SHOTS = [
  {
    src: "/screenshot-overview.webp",
    label: "the board · GET /",
    alt: "The TaskBridge dispatch board: live tallies for running, pending, waiting and filed, next to the task queue.",
    caption: "Live tallies and the docket queue, read straight from the SQLite store.",
  },
  {
    src: "/screenshot-docket.webp",
    label: "docket · live printout",
    alt: "A selected docket showing task metadata, permission, model and the agent's live printout with its final result.",
    caption: "Pick a docket and its printout streams in — commands, output, and the receipt.",
  },
];

/** Real screenshots of a live dispatch board: the stylized demo, grounded. */
export function Screenshots() {
  return (
    <section id="screenshots" aria-labelledby="screenshots-title" className="relative isolate">
      <AsciiRule />
      <div className="mx-auto max-w-6xl px-5 py-24 sm:px-8 md:py-32">
        <SectionHead
          id="screenshots-title"
          index="06"
          kicker="The real board"
          title="Not a mockup — this is it running."
          lede="Straight from a live TaskBridge instance. Self-host it and this is the board you get at GET /, on the same host as the MCP endpoint."
        />

        <div className="mt-14 grid gap-6 lg:grid-cols-2">
          {SHOTS.map((s) => (
            <Reveal key={s.src}>
              <figure className="term-card overflow-hidden">
                <div className="flex items-center gap-1.5 border-b border-line px-4 py-2.5" aria-hidden="true">
                  <span className="h-2 w-2 rounded-full bg-line" />
                  <span className="h-2 w-2 rounded-full bg-line" />
                  <span className="h-2 w-2 rounded-full bg-line" />
                  <span className="eyebrow ml-2 text-[10px]">{s.label}</span>
                </div>
                <img
                  src={s.src}
                  width={1600}
                  height={1000}
                  loading="lazy"
                  alt={s.alt}
                  className="block h-auto w-full"
                />
                <figcaption className="border-t border-line px-4 py-3 font-mono text-[12px] leading-[1.6] text-faint">
                  {s.caption}
                </figcaption>
              </figure>
            </Reveal>
          ))}
        </div>
      </div>
    </section>
  );
}
