import { NavLink, Link } from 'react-router-dom'

const links = [
  { to: '/architecture', label: 'how it works' },
  { to: '/quickstart', label: 'quickstart' },
  { to: '/faq', label: 'faq' },
]

function Nav() {
  return (
    <header className="nav">
      <div className="nav-inner">
        <Link to="/" className="nav-mark" aria-label="TaskBridge home">
          <span className="nav-glyph" aria-hidden="true">⇄</span> taskbridge
        </Link>
        <nav className="nav-links" aria-label="primary">
          {links.map(l => (
            <NavLink key={l.to} to={l.to} className={({ isActive }) => (isActive ? 'on' : '')}>
              {l.label}
            </NavLink>
          ))}
        </nav>
        <a
          className="btn btn-ghost nav-gh"
          href="https://github.com/Parithosh-Varma/TaskBridge"
          target="_blank"
          rel="noreferrer"
        >
          github ↗
        </a>
      </div>
    </header>
  )
}

function Footer() {
  return (
    <footer className="foot">
      <div className="foot-inner">
        <div className="foot-wire" aria-hidden="true">────────────────────────────────────────</div>
        <div className="foot-rows">
          <p className="foot-cr">
            claude plans<span className="dotsep"> · </span>opencode builds
            <span className="dotsep"> · </span>
            <a href="https://github.com/Parithosh-Varma/TaskBridge" target="_blank" rel="noreferrer">
              github ↗
            </a>
          </p>
          <p className="foot-dim">apache-2.0 — fork it, self-host it, build on it. static site · no trackers</p>
        </div>
      </div>
    </footer>
  )
}

export default function Layout({ children }) {
  return (
    <>
      <a className="skip" href="#top">skip to content</a>
      <Nav />
      <main id="top" className="page">{children}</main>
      <Footer />
    </>
  )
}
