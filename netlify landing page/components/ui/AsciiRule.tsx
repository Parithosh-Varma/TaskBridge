// A long run of ─ characters: longer than any viewport, clipped by its container.
const RUN = "─".repeat(900);

/** A full-width ─ rule, drawn as text. Decorative only; layout is the parent's job. */
export function AsciiRule({ className = "" }: { className?: string }) {
  return (
    <div aria-hidden="true" className={`ascii-rule ${className}`}>
      {RUN}
    </div>
  );
}
