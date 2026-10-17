import { CopyButton } from "./CopyButton";

interface CommandBlockProps {
  command: string;
  prompt?: string;
  className?: string;
}

/** A bordered, copyable shell line. Wraps on narrow screens instead of scrolling. */
export function CommandBlock({ command, prompt = "$", className = "" }: CommandBlockProps) {
  return (
    <div className={`term-card flex items-start gap-3 py-3 pr-3 pl-4 ${className}`}>
      <code className="min-w-0 flex-1 font-mono text-[13px] leading-6 break-all text-paper sm:break-words">
        <span className="mr-2 select-none text-signal" aria-hidden="true">
          {prompt}
        </span>
        {command}
      </code>
      <CopyButton text={command} />
    </div>
  );
}
