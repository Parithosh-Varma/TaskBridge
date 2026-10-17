import { useRef, useState } from 'react'

/**
 * A fenced code block with a copy affordance.
 * label  — small eyebrow above the block
 * code   — array of lines (keeps source readable)
 * accent — optional status hint under the block
 */
export default function Code({ label, code, accent }) {
  const text = Array.isArray(code) ? code.join('\n') : code
  const ref = useRef(null)
  const [copied, setCopied] = useState(false)

  const copy = async () => {
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(text)
      } else {
        ref.current?.select()
        document.execCommand('copy')
      }
      setCopied(true)
      setTimeout(() => setCopied(false), 1400)
    } catch {
      setCopied(false)
    }
  }

  return (
    <figure className="code">
      {label && <figcaption className="code-label">{label}</figcaption>}
      <div className="code-shell">
        <button type="button" className={'code-copy' + (copied ? ' done' : '')} onClick={copy}>
          {copied ? 'copied ✓' : 'copy'}
        </button>
        <pre className="art art-code"><code ref={ref}>{text}</code></pre>
      </div>
      {accent && <p className="code-accent">{accent}</p>}
    </figure>
  )
}
