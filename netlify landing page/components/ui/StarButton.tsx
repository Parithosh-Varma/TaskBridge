import { REPO_URL, formatStars } from "@/lib/github";

/** Primary CTA: amber-bordered, quiet until hovered. */
export function StarButton({ stars, className = "" }: { stars: number; className?: string }) {
  return (
    <a
      href={REPO_URL}
      target="_blank"
      rel="noreferrer"
      className={`group inline-flex items-center gap-2.5 rounded-[4px] border border-signal/70 bg-signal/[0.06] px-5 py-3 font-mono text-[13px] font-semibold tracking-wide text-signal transition-[background-color,border-color,box-shadow] duration-300 hover:border-signal hover:bg-signal/[0.12] hover:shadow-[0_0_24px_-6px_rgba(242,160,7,0.5)] ${className}`}
    >
      <span aria-hidden="true">★</span>
      Star on GitHub
      <span className="border-l border-signal/40 pl-2.5 tabular-nums text-signal/80" aria-label={`${stars} stars`}>
        {formatStars(stars)}
      </span>
    </a>
  );
}
