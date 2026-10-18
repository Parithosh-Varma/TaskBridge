"use client";

import { AnimatePresence, motion, useMotionValueEvent, useScroll, useSpring } from "motion/react";
import { useCallback, useEffect, useRef, useState } from "react";
import { GithubMark } from "@/components/ui/GithubMark";
import { ThemeToggle } from "@/components/ui/ThemeToggle";
import { AsciiRule } from "@/components/ui/AsciiRule";
import { REPO_URL, formatStars } from "@/lib/github";

const LINKS = [
  { href: "#why", label: "Why" },
  { href: "#features", label: "Features" },
  { href: "#quickstart", label: "Quickstart" },
  { href: "#demo", label: "Demo" },
  { href: "#faq", label: "FAQ" },
] as const;

/** Stable reference, so the scroll-spy effect does not re-subscribe on every render. */
const HREFS: readonly string[] = LINKS.map((l) => l.href);

/** Comfortably below the 3.5rem header, so an anchored section is active on arrival. */
const ACTIVE_LINE = 160;
const EASE_OUT = [0.16, 1, 0.3, 1] as const;

/** The desktop list and the drawer both render, but only one of them is on screen. */
function isRendered(el: HTMLElement): boolean {
  // `getClientRects` is empty for `display: none`; unlike `offsetParent` it is not fooled by
  // fixed-position ancestors (the drawer's wrapper is one).
  return el.getClientRects().length > 0;
}

/**
 * Marks the link for the section the reader is actually in. Writes `aria-current` and
 * `data-active` straight to the DOM: the drawer mounts more than one link per section,
 * and only the visible ones may announce themselves.
 *
 * Returns the update, so callers can re-mark after the drawer mounts.
 */
function useActiveSection(hrefs: readonly string[]) {
  const update = useCallback(() => {
    const line = window.scrollY + ACTIVE_LINE;
    let next: string | null = null;
    for (const href of hrefs) {
      const el = document.querySelector(`section${href}`);
      if (el && el.getBoundingClientRect().top + window.scrollY <= line) next = href;
    }
    document.querySelectorAll<HTMLElement>("[data-nav-link]").forEach((link) => {
      const current = link.dataset.navLink === next && isRendered(link);
      if (current) link.setAttribute("aria-current", "true");
      else link.removeAttribute("aria-current");
      link.toggleAttribute("data-active", current);
    });
  }, [hrefs]);

  useEffect(() => {
    let frame = 0;
    const schedule = () => {
      if (!frame) frame = requestAnimationFrame(() => {
        frame = 0;
        update();
      });
    };
    schedule();
    // Section boundaries move when content above them shifts, without a scroll event.
    window.addEventListener("scroll", schedule, { passive: true });
    window.addEventListener("resize", schedule);
    const observer = new ResizeObserver(schedule);
    observer.observe(document.documentElement);
    return () => {
      if (frame) cancelAnimationFrame(frame);
      window.removeEventListener("scroll", schedule);
      window.removeEventListener("resize", schedule);
      observer.disconnect();
    };
  }, [update]);

  return update;
}

export function Nav({ stars }: { stars: number }) {
  const { scrollY, scrollYProgress } = useScroll();
  const progress = useSpring(scrollYProgress, { stiffness: 320, damping: 40, restDelta: 0.001 });
  const [scrolled, setScrolled] = useState(false);
  const [open, setOpen] = useState(false);
  const markActive = useActiveSection(HREFS);

  // The drawer only exists while open, so it needs a (re)mark once it is on screen.
  useEffect(() => {
    if (open) markActive();
  }, [open, markActive]);

  useMotionValueEvent(scrollY, "change", (y) => setScrolled(y > 8));

  // A pointer-driven change to the viewport must not leave a stale drawer mounted.
  useEffect(() => {
    const wide = window.matchMedia("(min-width: 48rem)");
    const onChange = () => {
      if (wide.matches) setOpen(false);
    };
    wide.addEventListener("change", onChange);
    return () => wide.removeEventListener("change", onChange);
  }, []);

  // The drawer owns the scroll while it is open.
  useEffect(() => {
    document.body.style.overflow = open ? "hidden" : "";
    return () => {
      document.body.style.overflow = "";
    };
  }, [open]);

  const wasOpen = useRef(false);
  const toggleRef = useRef<HTMLButtonElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    // `preventScroll` keeps this focus movement from yanking the page.
    if (open) panelRef.current?.focus({ preventScroll: true });
    else if (wasOpen.current) toggleRef.current?.focus({ preventScroll: true });
    wasOpen.current = open;
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open]);

  // Keep Tab inside the drawer while it is open.
  const trapTab = useCallback((e: React.KeyboardEvent<HTMLDivElement>) => {
    if (e.key !== "Tab" || !panelRef.current) return;
    const focusable = Array.from(panelRef.current.querySelectorAll<HTMLElement>("a[href]"));
    if (focusable.length === 0) return;
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (e.shiftKey && document.activeElement === first) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault();
      first.focus();
    }
  }, []);

  return (
    <>
      <header
        data-scrolled={scrolled || undefined}
        className="sticky top-0 z-50 bg-bg/80 backdrop-blur-md transition-[background-color] duration-300 ease-[var(--ease-out)] data-[scrolled]:bg-bg/92 supports-[backdrop-filter]:bg-bg/70 supports-[backdrop-filter]:data-[scrolled]:bg-bg/85"
      >
        <nav aria-label="Primary" className="relative mx-auto flex h-14 max-w-6xl items-center justify-between gap-6 px-5 sm:px-8">
          <AsciiRule className="pointer-events-none absolute inset-x-0 bottom-0" />
          <a href="#top" className="group flex shrink-0 items-center gap-2.5 font-mono text-[14px] font-semibold tracking-[-0.01em] text-paper">
            <img src="/logo-dark.png" alt="" width={480} height={162} className="logo-dark h-[18px] w-auto shrink-0" />
            <img src="/logo-light.png" alt="" width={480} height={162} className="logo-light h-[18px] w-auto shrink-0" />
            TaskBridge
            <span className="hidden items-center gap-1.5 font-mono text-[10px] font-medium uppercase tracking-[0.2em] text-signal sm:inline-flex">
              <span aria-hidden="true" className="animate-lamp">*</span> live
            </span>
          </a>

          <div className="flex min-w-0 items-center gap-1 sm:gap-2">
            <ul className="hidden items-center md:flex">
              {LINKS.map((l) => (
                <li key={l.href}>
                  <a
                    href={l.href}
                    data-nav-link={l.href}
                    className="relative block px-3 py-2 font-mono text-[12px] tracking-[0.04em] text-faint transition-colors duration-200 hover:text-paper data-[active]:text-signal"
                  >
                    {l.label}
                    <span
                      aria-hidden="true"
                      className="absolute inset-x-3 -bottom-px h-[2px] origin-left scale-x-0 bg-[image:var(--ramp)] transition-transform duration-300 ease-[var(--ease-out)] data-[active]:scale-x-100"
                    />
                  </a>
                </li>
              ))}
            </ul>

            <a
              href={REPO_URL}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-2 border border-line px-3 py-1.5 font-mono text-[12px] text-paper transition-colors duration-200 hover:border-signal/60 hover:bg-panel"
            >
              <GithubMark size={14} />
              <span aria-hidden="true" className="text-signal">*</span>
              <span className="hidden tabular-nums sm:inline">{formatStars(stars)}</span>
              <span className="sr-only">TaskBridge on GitHub, {stars} stars</span>
            </a>

            <ThemeToggle />

            <button
              ref={toggleRef}
              type="button"
              aria-expanded={open}
              aria-controls="mobile-nav"
              aria-label={open ? "Close menu" : "Menu"}
              onClick={() => setOpen((o) => !o)}
              className="relative -mr-1 z-[45] inline-flex h-9 w-9 shrink-0 items-center justify-center border border-line bg-bg font-mono text-[13px] text-paper transition-colors duration-200 hover:border-signal/60 hover:bg-panel md:hidden"
            >
              <span aria-hidden="true">{open ? "[x]" : "[=]"}</span>
            </button>
          </div>

          <motion.span
            aria-hidden="true"
            style={{ scaleX: progress }}
            className="pointer-events-none absolute inset-x-0 -bottom-px h-[2px] origin-left bg-[image:var(--ramp)]"
          />
        </nav>
      </header>

      {/* Outside the header: its backdrop-filter makes it a containing block for fixed children. */}
      <AnimatePresence>
        {open && (
          <div className="fixed inset-x-0 top-[calc(3.5rem+2px)] bottom-0 z-40 md:hidden">
            <motion.div
              key="backdrop"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.22, ease: EASE_OUT }}
              aria-hidden="true"
              className="absolute inset-0 bg-bg/60 backdrop-blur-[2px]"
              onClick={() => setOpen(false)}
            />
            <motion.div
              key="drawer"
              id="mobile-nav"
              ref={panelRef}
              role="dialog"
              aria-modal="true"
              aria-label="Sections"
              tabIndex={-1}
              initial={{ opacity: 0, y: -10 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -10 }}
              transition={{ duration: 0.26, ease: EASE_OUT }}
              onKeyDown={trapTab}
              className="relative max-h-full overflow-y-auto border-b border-line bg-panel px-5 pt-2 pb-4 shadow-[0_24px_48px_-24px_rgba(0,0,0,0.9)] focus-visible:outline-none"
            >
              <ul className="divide-y divide-line/60">
                {LINKS.map((l, i) => (
                  <li key={l.href}>
                    <a
                      href={l.href}
                      data-nav-link={l.href}
                      onClick={() => setOpen(false)}
                      className="flex items-baseline gap-4 py-3.5 font-mono text-[14px] text-paper/85 transition-colors hover:text-paper data-[active]:text-signal"
                    >
                      <span
                        aria-hidden="true"
                        className="text-[10px] tabular-nums text-faint data-[active]:text-signal"
                      >
                        {String(i + 1).padStart(2, "0")}
                      </span>
                      {l.label}
                    </a>
                  </li>
                ))}
              </ul>
              <a
                href={REPO_URL}
                target="_blank"
                rel="noreferrer"
                className="mt-3 flex items-center justify-between border border-line bg-bg px-3 py-2.5 font-mono text-[12px] text-paper/85 transition-colors hover:border-signal/60 hover:text-paper"
              >
                <span className="inline-flex items-center gap-2">
                  <GithubMark size={14} />
                  Star on GitHub
                </span>
                <span aria-hidden="true" className="text-signal">
                  * {formatStars(stars)}
                </span>
              </a>
            </motion.div>
          </div>
        )}
      </AnimatePresence>
    </>
  );
}
