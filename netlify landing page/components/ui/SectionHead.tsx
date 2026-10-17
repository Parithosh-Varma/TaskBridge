import type { ReactNode } from "react";
import { Reveal } from "./Reveal";

interface SectionHeadProps {
  index: string;
  kicker: string;
  title: ReactNode;
  lede?: ReactNode;
  id?: string;
  className?: string;
}

export function SectionHead({ index, kicker, title, lede, id, className = "" }: SectionHeadProps) {
  return (
    <Reveal className={`max-w-2xl ${className}`}>
      <p className="eyebrow">
        <span className="text-signal">{index}</span>
        <span className="mx-2 text-line">/</span>
        {kicker}
      </p>
      <h2 id={id} className="mt-4 font-mono text-[28px] leading-[1.12] font-bold tracking-[-0.03em] text-paper sm:text-[36px]">
        {title}
      </h2>
      {lede ? <p className="mt-4 text-[16px] leading-[1.65] text-paper/75">{lede}</p> : null}
    </Reveal>
  );
}
