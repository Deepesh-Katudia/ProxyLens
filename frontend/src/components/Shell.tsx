import type { ReactNode } from 'react'
import { Link } from '../lib/router'

const NAV = [
  { to: '/', label: 'Analyse' },
  { to: '/eval', label: 'Evaluation' },
  { to: '/about', label: 'About' },
  { to: '/label', label: 'Gold labels' },
]

function active(path: string, to: string): boolean {
  if (to === '/') return path === '/' || path.startsWith('/documents')
  return path.startsWith(to)
}

export function Shell({ path, children }: { path: string; children: ReactNode }) {
  return (
    <div className="flex min-h-screen flex-col">
      <header className="border-b border-ink/10 bg-paper/90 backdrop-blur">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-4 px-6 py-4">
          <Link to="/" className="group flex items-baseline gap-2">
            <span className="font-display text-2xl font-semibold tracking-tight">ProxyLens</span>
            <span className="hidden text-xs uppercase tracking-[0.2em] text-ink/45 sm:inline">AGM resolution analyst</span>
          </Link>
          <nav aria-label="Main navigation" className="flex gap-1 text-sm">
            {NAV.map((item) => (
              <Link
                key={item.to}
                to={item.to}
                className={`rounded px-3 py-1.5 transition-colors ${
                  active(path, item.to) ? 'bg-ink text-paper' : 'text-ink/70 hover:bg-ink/5 hover:text-ink'
                }`}
              >
                {item.label}
              </Link>
            ))}
          </nav>
        </div>
      </header>
      <main className="mx-auto w-full max-w-6xl flex-1 px-6 py-10">{children}</main>
      <footer className="border-t border-ink/10">
        <p className="mx-auto max-w-6xl px-6 py-5 text-xs text-ink/55">
          Research and educational tool. Not investment or voting advice. Recommendations are a first pass for a human
          analyst and must be checked against the notice and the current law.
        </p>
      </footer>
    </div>
  )
}
