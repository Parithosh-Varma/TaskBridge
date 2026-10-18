"use client";

/**
 * Vendored from the shadcn/magicui `terminal` registry item (magicui.design/r/terminal)
 * and adapted to the house style:
 *  - the macOS dots header became our ASCII window bar (`- + x` + eyebrow title)
 *  - magicui's bundled typography (`text-sm font-normal tracking-tight`) is gone;
 *    callers size and color lines through `className`
 *  - `TypingAnimation` gained a `prefix` slot rendered while typing runs,
 *    so a command line can show its `> ` prompt in a different tone
 *  - per-line "my turn" latches are derived from the monotonic `activeIndex`
 *    instead of setState-in-effect (the repo's react-hooks rule forbids that)
 */

import {
  Children,
  createContext,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { motion, useInView } from "motion/react";

const cn = (...classes: Array<string | false | undefined>) => classes.filter(Boolean).join(" ");

interface SequenceContextValue {
  completeItem: (index: number) => void;
  activeIndex: number;
  sequenceStarted: boolean;
}

const SequenceContext = createContext<SequenceContextValue | null>(null);
const useSequence = () => useContext(SequenceContext);

const ItemIndexContext = createContext<number | null>(null);
const useItemIndex = () => useContext(ItemIndexContext);

interface AnimatedSpanProps {
  children: ReactNode;
  /** Standalone mode: ms to wait before revealing. Ignored inside a sequence. */
  delay?: number;
  className?: string;
  /** Standalone mode: wait until scrolled into view. Ignored inside a sequence. */
  startOnView?: boolean;
}

export const AnimatedSpan = ({ children, delay = 0, className, startOnView = false }: AnimatedSpanProps) => {
  const elementRef = useRef<HTMLDivElement | null>(null);
  const isInView = useInView(elementRef as React.RefObject<Element>, { amount: 0.3, once: true });

  const sequence = useSequence();
  const itemIndex = useItemIndex();

  // activeIndex only moves forward, so `>=` is a one-way reveal:
  // a line that has played stays visible once its turn has passed.
  const shouldAnimate = sequence
    ? itemIndex !== null && sequence.sequenceStarted && sequence.activeIndex >= itemIndex
    : startOnView
      ? isInView
      : true;

  return (
    <motion.div
      ref={elementRef}
      initial={{ opacity: 0, y: -5 }}
      animate={shouldAnimate ? { opacity: 1, y: 0 } : { opacity: 0, y: -5 }}
      transition={{ duration: 0.3, delay: sequence ? 0 : delay / 1000 }}
      className={cn("whitespace-pre", className)}
      onAnimationComplete={() => {
        if (!sequence || itemIndex === null) return;
        sequence.completeItem(itemIndex);
      }}
    >
      {children}
    </motion.div>
  );
};

interface TypingAnimationProps {
  children: string;
  className?: string;
  /** ms per character. */
  duration?: number;
  /** Standalone mode: ms to wait before typing starts. Ignored inside a sequence. */
  delay?: number;
  /** Rendered while the line types (e.g. a colored `> ` prompt). */
  prefix?: ReactNode;
  /** Standalone mode: wait until scrolled into view. Ignored inside a sequence. */
  startOnView?: boolean;
}

export const TypingAnimation = ({
  children: text,
  className,
  duration = 60,
  delay = 0,
  prefix,
  startOnView = true,
}: TypingAnimationProps) => {
  if (typeof text !== "string") {
    throw new Error("TypingAnimation: children must be a string.");
  }

  const [displayedText, setDisplayedText] = useState("");
  const [standaloneStarted, setStandaloneStarted] = useState(false);
  const elementRef = useRef<HTMLSpanElement | null>(null);
  const isInView = useInView(elementRef as React.RefObject<Element>, { amount: 0.3, once: true });

  const sequence = useSequence();
  const itemIndex = useItemIndex();
  const inSequence = sequence !== null && itemIndex !== null;

  // In sequence mode it is exactly this line's turn; standalone mode latches
  // its own start through the timeout below.
  const started =
    sequence && itemIndex !== null
      ? sequence.sequenceStarted && sequence.activeIndex === itemIndex
      : standaloneStarted;

  const completeItemRef = useRef<SequenceContextValue["completeItem"] | null>(null);
  const itemIndexRef = useRef<number | null>(null);

  useEffect(() => {
    completeItemRef.current = sequence?.completeItem ?? null;
    itemIndexRef.current = itemIndex;
  }, [sequence?.completeItem, itemIndex]);

  useEffect(() => {
    if (inSequence) return;
    if (startOnView && !isInView) return;
    const startTimeout = setTimeout(() => setStandaloneStarted(true), delay);
    return () => clearTimeout(startTimeout);
  }, [inSequence, delay, startOnView, isInView]);

  useEffect(() => {
    if (!started) return;

    let i = 0;
    const typingEffect = setInterval(() => {
      if (i < text.length) {
        i++;
        setDisplayedText(text.substring(0, i));
      } else {
        clearInterval(typingEffect);
        const completeItem = completeItemRef.current;
        const idx = itemIndexRef.current;
        if (completeItem && idx !== null) completeItem(idx);
      }
    }, duration);

    return () => clearInterval(typingEffect);
  }, [text, duration, started]);

  return (
    <motion.span ref={elementRef} className={cn("whitespace-pre", className)}>
      {displayedText.length > 0 ? prefix : null}
      {displayedText}
    </motion.span>
  );
};

interface TerminalProps {
  children: ReactNode;
  className?: string;
  /** Title in the ASCII window bar. */
  title?: string;
  /** Accessible description for the session shown inside (turns the `<pre>` into role="img"). */
  label?: string;
  /** Play children one after another as they complete (the magicui sequence engine). */
  sequence?: boolean;
  /** In sequence mode, start once scrolled into view. */
  startOnView?: boolean;
}

export const Terminal = ({
  children,
  className,
  title = "claude / taskbridge mcp / illustrative session",
  label,
  sequence = true,
  startOnView = true,
}: TerminalProps) => {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const isInView = useInView(containerRef as React.RefObject<Element>, { amount: 0.3, once: true });

  const [activeIndex, setActiveIndex] = useState(0);
  const sequenceHasStarted = sequence ? !startOnView || isInView : false;

  const contextValue = useMemo<SequenceContextValue | null>(() => {
    if (!sequence) return null;
    return {
      completeItem: (index: number) => {
        setActiveIndex((current) => (index === current ? current + 1 : current));
      },
      activeIndex,
      sequenceStarted: sequenceHasStarted,
    };
  }, [sequence, activeIndex, sequenceHasStarted]);

  const wrappedChildren = useMemo(() => {
    if (!sequence) return children;
    return Children.toArray(children).map((child, index) => (
      <ItemIndexContext.Provider key={index} value={index}>
        {child}
      </ItemIndexContext.Provider>
    ));
  }, [children, sequence]);

  const content = (
    <div ref={containerRef} className={cn("flex h-full flex-col", className)}>
      <div className="flex items-center justify-between border-b border-line px-4 py-2.5">
        <div className="flex items-center gap-2 font-mono text-[12px] leading-none text-line" aria-hidden="true">
          <span>-</span>
          <span>+</span>
          <span>x</span>
        </div>
        <p className="eyebrow text-[10px]">{title}</p>
      </div>
      <pre role={label ? "img" : undefined} aria-label={label} className="overflow-x-auto px-4 py-4">
        <code className="grid w-max gap-y-1 font-mono text-[11.5px] leading-[1.7] sm:text-[12.5px]">{wrappedChildren}</code>
      </pre>
    </div>
  );

  if (!sequence) return content;
  return <SequenceContext.Provider value={contextValue}>{content}</SequenceContext.Provider>;
};
