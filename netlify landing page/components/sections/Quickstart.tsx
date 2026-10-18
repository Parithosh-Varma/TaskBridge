import { AsciiTexture } from "@/components/ascii/AsciiTexture";
import { AsciiRule } from "@/components/ui/AsciiRule";
import { CommandBlock } from "@/components/ui/CommandBlock";
import { Reveal } from "@/components/ui/Reveal";
import { SectionHead } from "@/components/ui/SectionHead";
import { INSTALL_ONE_LINER } from "@/lib/content";
import { README_URL } from "@/lib/github";
import type { ReactNode } from "react";

const CONNECTOR_BOX = [
  "┌─ TaskBridge connector ─────────────────────────────┐",
  "│                                                    │",
  "│  URL    https://<your-domain>.ngrok.app/mcp        │",
  "│  Token  ****************************************   │",
  "│                                                    │",
  "└────────────────────────────────────────────────────┘",
];

const FLOW = [
  { call: 'submit_task(title=..., instructions=..., working_dir=...)', ret: "id" },
  { call: 'wait_for(task_ids=["<id>"], timeout_sec=120)', ret: "blocks -- no polling" },
  { call: 'get_task_result(task_id="<id>")', ret: "result | structured | usage | diff" },
];

function Step({ n, title, children }: { n: string; title: string; children: ReactNode }) {
  return (
    <Reveal as="li" className="sep-t grid gap-5 pt-8 md:grid-cols-[7rem_1fr] md:gap-8">
      <div className="flex items-baseline gap-3 md:block">
        <span className="font-mono text-[34px] leading-none font-bold tracking-[-0.04em] text-signal md:text-[44px]">{n}</span>
        <span className="eyebrow md:mt-3 md:block">of 03</span>
      </div>
      <div className="min-w-0">
        <h3 className="font-mono text-[18px] font-semibold tracking-[-0.01em] text-paper">{title}</h3>
        {children}
      </div>
    </Reveal>
  );
}

export function Quickstart() {
  return (
    <section id="quickstart" aria-labelledby="quickstart-title" className="relative isolate">
      <AsciiRule />
      <AsciiTexture variant="margin" />
      <div className="mx-auto max-w-6xl px-5 py-24 sm:px-8 md:py-32">
        <SectionHead id="quickstart-title" index="04" kicker="Three moves" title="From clone to first receipt." />

        <ol className="mt-14 space-y-12">
          <Step n="01" title="Clone and install">
            <p className="mt-2 max-w-2xl text-[15px] leading-[1.6] text-paper/75">
              <code className="font-mono text-[13px] text-paper">install.sh</code> installs dependencies into{" "}
              <code className="font-mono text-[13px] text-paper">.venv</code>, generates or reuses your bearer token,
              opens the ngrok tunnel, pairs <code className="font-mono text-[13px] text-paper">MCP_ALLOWED_HOSTS</code>,
              prints your connector box, and serves MCP in the foreground.
            </p>
            <CommandBlock command={INSTALL_ONE_LINER} className="mt-5" />
          </Step>

          <Step n="02" title="Read your connector box">
            <p className="mt-2 max-w-2xl text-[15px] leading-[1.6] text-paper/75">
              The public URL plus the bearer token. <code className="font-mono text-[13px] text-paper">/mcp</code> and{" "}
              <code className="font-mono text-[13px] text-paper">/api/*</code> require it;{" "}
              <code className="font-mono text-[13px] text-paper">/health</code> stays open. Rotate any time with{" "}
              <code className="font-mono text-[13px] text-paper">./install.sh --rotate</code>.
            </p>
            <div className="term-card mt-5 overflow-x-auto bg-bg px-4 py-4">
              <pre
                role="img"
                aria-label="Example output: a box showing your public MCP URL and a masked bearer token"
                className="w-max font-mono text-[12px] leading-[1.6] text-faint sm:text-[13px]"
              >
                {CONNECTOR_BOX.join("\n")}
              </pre>
            </div>
          </Step>

          <Step n="03" title="Dispatch from Claude">
            <p className="mt-2 max-w-2xl text-[15px] leading-[1.6] text-paper/75">
              Add the URL as an MCP connector — or wire stdio into Claude Desktop — then ask Claude to hand work over.
            </p>
            <div className="term-card mt-5 divide-y divide-line">
              {FLOW.map((f, i) => (
                <div key={f.call} className="flex flex-col gap-1 px-4 py-3 sm:flex-row sm:items-center sm:justify-between sm:gap-6">
                  <code className="font-mono text-[13px] break-all text-paper">
                    <span className="mr-3 text-faint">{i + 1}</span>
                    {f.call}
                  </code>
                  <span className="font-mono text-[12px] whitespace-nowrap text-seal">-&gt; {f.ret}</span>
                </div>
              ))}
            </div>
          </Step>
        </ol>

        <Reveal className="mt-12 flex flex-col gap-3 border-t border-line pt-6 font-mono text-[13px] text-faint sm:flex-row sm:items-center sm:justify-between">
          <p>
            Prerequisites: Python 3.12 / <code className="text-paper/85">opencode</code> on PATH / a free ngrok account
            for public access.
          </p>
          <a
            href={README_URL}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1.5 text-paper/85 underline decoration-line underline-offset-4 transition-colors hover:text-signal hover:decoration-signal"
          >
            Full README <span aria-hidden="true">-&gt;</span>
          </a>
        </Reveal>
      </div>
    </section>
  );
}
