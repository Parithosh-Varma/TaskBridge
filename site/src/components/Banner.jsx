import { BANNERS } from '../banners.js'

/** Figlet banner pre-rendered at build time. */
export default function Banner({ word, className = '' }) {
  const art = BANNERS[word]
  if (!art) return null
  return <pre className={'banner ' + className} aria-hidden="true">{art}</pre>
}
