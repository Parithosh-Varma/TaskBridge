"use client";

import { useEffect, useRef, useState } from "react";

interface CopyButtonProps {
  text: string;
  label?: string;
  className?: string;
}

export function CopyButton({ text, label = "Copy command", className = "" }: CopyButtonProps) {
  const [copied, setCopied] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => () => {
    if (timer.current) clearTimeout(timer.current);
  }, []);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      return;
    }
    setCopied(true);
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => setCopied(false), 1500);
  };

  return (
    <button
      type="button"
      onClick={copy}
      aria-label={copied ? "Copied" : label}
      className={`inline-flex shrink-0 items-center gap-1.5 border border-line px-2.5 py-1.5 font-mono text-[11px] uppercase tracking-[0.14em] text-faint transition-colors duration-200 hover:border-signal/60 hover:bg-panel-2 hover:text-paper ${copied ? "border-seal/60 text-seal" : ""} ${className}`}
    >
      <span aria-hidden="true">{copied ? "[ok]" : "[+]"}</span>
      <span aria-live="polite">{copied ? "Copied" : "Copy"}</span>
    </button>
  );
}
