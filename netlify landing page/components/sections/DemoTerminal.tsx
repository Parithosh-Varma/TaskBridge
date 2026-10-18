"use client";

import { AnimatedSpan, Terminal, TypingAnimation } from "@/components/magicui/terminal";
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

const PROMPT = <span className="select-none text-signal">&gt; </span>;

/** ms per typed character -- long command lines still finish with a beat. */
const TYPE_DURATION = 20;

const LABEL =
  "Illustrative session: Claude submits a task, the worker pauses with a question, Claude answers with answer_task, the run resumes, and get_task_result returns a summary, files touched, tests run, and a diff.";

const lineClass = (tone: TermTone) => `block whitespace-pre ${TONE[tone]}`;

const isCmdStart = (text: string, typed?: boolean) => Boolean(typed) && !text.startsWith(" ");

export function DemoTerminal({ reduced }: { reduced: boolean }) {
  if (reduced) {
    return (
      <Terminal label={LABEL} sequence={false} className="term-card overflow-hidden bg-term">
        {TERMINAL_SCRIPT.map((l, i) => (
          <span key={i} className={lineClass(l.tone)}>
            {isCmdStart(l.text, l.typed) ? PROMPT : null}
            {l.text}
          </span>
        ))}
      </Terminal>
    );
  }

  return (
    <Terminal label={LABEL} className="term-card overflow-hidden bg-term">
      {TERMINAL_SCRIPT.map((l, i) =>
        l.typed ? (
          <TypingAnimation
            key={i}
            duration={TYPE_DURATION}
            className={lineClass(l.tone)}
            prefix={isCmdStart(l.text, l.typed) ? PROMPT : undefined}
          >
            {l.text}
          </TypingAnimation>
        ) : (
          <AnimatedSpan key={i} className={lineClass(l.tone)}>
            {l.text}
          </AnimatedSpan>
        ),
      )}
    </Terminal>
  );
}
