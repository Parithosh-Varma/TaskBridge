import { Link } from 'react-router-dom'

export default function NotFound() {
  return (
    <article className="pagehead">
      <p className="eyebrow">404 · not on the manifest</p>
      <h1 className="page-h">
        <span className="mono-shrug">¯\_(ツ)_/¯</span>
      </h1>
      <p className="sub">
        This address isn't on the manifest. The queue has no such task — but the bridge is a
        keystroke away:
      </p>
      <p className="notfound-links">
        <Link className="btn btn-solid" to="/">back to the landing →</Link>
        <Link className="btn btn-ghost" to="/quickstart">quickstart</Link>
      </p>
    </article>
  )
}
