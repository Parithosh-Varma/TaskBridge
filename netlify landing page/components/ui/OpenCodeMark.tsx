/**
 * OpenCode's block mark: an outlined window with its lower half filled.
 * Inlined from the official favicon (opencode.ai) since it is not part of lucide.
 * The inner block inherits the frame color at reduced opacity, matching the two-tone original.
 */
export function OpenCodeMark({ size, className }: { size?: number; className?: string }) {
  return (
    <svg viewBox="0 0 512 512" width={size} height={size} aria-hidden="true" className={className}>
      <path
        d="M384 416H128V96H384V416ZM320 160H192V352H320V160Z"
        fill="currentColor"
        fillRule="evenodd"
        clipRule="evenodd"
      />
      <path d="M320 224V352H192V224H320Z" fill="currentColor" fillOpacity="0.45" />
    </svg>
  );
}
