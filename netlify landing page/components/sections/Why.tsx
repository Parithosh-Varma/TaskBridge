import { ClaudeMark } from "@/components/ui/ClaudeMark";
import { OpenCodeMark } from "@/components/ui/OpenCodeMark";
import { SQLiteMark } from "@/components/ui/SQLiteMark";
import { Reveal } from "@/components/ui/Reveal";
import { AsciiTexture } from "@/components/ascii/AsciiTexture";
import { AsciiRule } from "@/components/ui/AsciiRule";

const ROLES = [
  {
    mark: ClaudeMark,
    tone: "text-ember",
    name: "The planner",
    body: "Claude stays the interface. It breaks work down, delegates, and reads results.",
  },
  {
    mark: OpenCodeMark,
    tone: "text-seal",
    name: "The executor",
    body: "OpenCode does the execution — edits, tests, shell — headlessly and reproducibly.",
  },
  {
    mark: SQLiteMark,
    tone: "text-signal",
    name: "The queue",
    body: "SQLite is the durable handoff. It survives restarts and supports retries, priorities, dependencies, and two-way questions.",
  },
];

export function Why() {
  return (
    <section id="why" aria-labelledby="why-title" className="relative isolate">
      <AsciiRule />
      <AsciiTexture variant="margin" />
      <div className="mx-auto grid max-w-6xl gap-14 px-5 py-24 sm:px-8 md:grid-cols-[1.15fr_1fr] md:gap-20 md:py-32">
        <Reveal>
          <p className="eyebrow">
            <span className="text-signal">01</span>
            <span className="mx-2 text-line">/</span>
            Out of context
          </p>
          <h2
            id="why-title"
            className="mt-4 font-mono text-[28px] leading-[1.12] font-bold tracking-[-0.03em] text-paper sm:text-[36px]"
          >
            Two good tools, standing on opposite platforms.
          </h2>
          <div className="mt-6 max-w-[36rem] space-y-4 text-[16px] leading-[1.7] text-paper/80">
            <p>
              Claude is a powerful planner that can&apos;t touch your filesystem. OpenCode runs code locally, but it
              lives outside Claude&apos;s context. Each is missing the half the other has.
            </p>
            <p>
              TaskBridge closes the loop. Claude writes a task to a queue over MCP. A worker on your machine picks it
              up, runs it in an isolated worktree, and files a receipt Claude can read: what changed, what ran, what is
              still open.
            </p>
          </div>
        </Reveal>

        <ul className="flex flex-col justify-end md:pt-24">
          {ROLES.map((r, i) => (
            <Reveal
              as="li"
              key={r.name}
              delay={i * 0.08}
              className={`flex gap-5 sep-t py-6 ${i === ROLES.length - 1 ? "sep-b" : ""}`}
            >
              <r.mark size={20} className={`mt-0.5 shrink-0 ${r.tone}`} />
              <div>
                <p className="font-mono text-[12px] uppercase tracking-[0.18em] text-faint">{r.name}</p>
                <p className="mt-2 text-[15px] leading-[1.6] text-paper/85">{r.body}</p>
              </div>
            </Reveal>
          ))}
        </ul>
      </div>

      <Reveal className="mx-auto max-w-6xl px-5 pb-24 sm:px-8 md:pb-32">
        <blockquote className="ascii-corners py-2 pr-6 pl-6 md:ml-[8%] md:max-w-[46rem]">
          <p className="font-mono text-[20px] leading-[1.45] font-semibold tracking-[-0.015em] text-signal sm:text-[24px]">
            Claude stays the interface. OpenCode does the execution. SQLite is the durable handoff.
          </p>
          <footer className="eyebrow mt-4">README / Why this exists</footer>
        </blockquote>
      </Reveal>
    </section>
  );
}
