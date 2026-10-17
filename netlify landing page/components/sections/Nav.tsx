import { GithubMark } from "@/components/ui/GithubMark";
import { REPO_URL, formatStars } from "@/lib/github";

const LINKS = [
  { href: "#why", label: "Why" },
  { href: "#features", label: "Features" },
  { href: "#quickstart", label: "Quickstart" },
  { href: "#demo", label: "Demo" },
  { href: "#faq", label: "FAQ" },
];

export function Nav({ stars }: { stars: number }) {
  return (
    <header className="sticky top-0 z-50 border-b border-line bg-bg/80 backdrop-blur-md supports-[backdrop-filter]:bg-bg/70">
      <nav aria-label="Primary" className="mx-auto flex h-14 max-w-6xl items-center justify-between gap-6 px-5 sm:px-8">
        <a href="#top" className="group flex items-center gap-3 font-mono text-[14px] font-semibold tracking-[-0.01em] text-paper">
          <span aria-hidden="true" className="text-faint transition-colors group-hover:text-signal">
            [═]
          </span>
          TaskBridge
          <span className="hidden items-center gap-1.5 font-mono text-[10px] font-medium uppercase tracking-[0.2em] text-signal sm:inline-flex">
            <span aria-hidden="true" className="animate-lamp">●</span> live
          </span>
        </a>
        <div className="flex items-center gap-1 sm:gap-2">
          <ul className="hidden items-center md:flex">
            {LINKS.map((l) => (
              <li key={l.href}>
                <a
                  href={l.href}
                  className="rounded-[3px] px-3 py-2 font-mono text-[12px] tracking-[0.04em] text-faint transition-colors duration-200 hover:text-paper"
                >
                  {l.label}
                </a>
              </li>
            ))}
          </ul>
          <a
            href={REPO_URL}
            target="_blank"
            rel="noreferrer"
            className="ml-2 inline-flex items-center gap-2 rounded-[3px] border border-line px-3 py-1.5 font-mono text-[12px] text-paper transition-colors duration-200 hover:border-signal/60 hover:bg-panel"
          >
            <GithubMark size={14} />
            <span className="sr-only">TaskBridge on GitHub,</span>
            <span className="text-signal" aria-hidden="true">★</span>
            <span className="tabular-nums">{formatStars(stars)}</span>
            <span className="sr-only">stars</span>
          </a>
        </div>
      </nav>
    </header>
  );
}
