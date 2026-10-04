import { useState } from 'react'
import { fetchRegulation } from '../../lib/api'
import type { Citation, RegulationView } from '../../lib/types'

type Opened = { id: string; state: 'loading' } | { id: string; state: 'ready'; chunk: RegulationView } | { id: string; state: 'error'; message: string }

const squash = (s: string) => s.replace(/\s+/g, ' ').trim()

// The quote is verified server-side as a whitespace-normalised substring; mark it in the chunk.
function Highlighted({ text, quote }: { text: string; quote: string }) {
  const flat = squash(text)
  const at = flat.indexOf(squash(quote))
  if (at < 0) return <>{flat}</>
  const end = at + squash(quote).length
  return (
    <>
      {flat.slice(0, at)}
      <mark className="rounded-sm bg-review/30 px-0.5 text-ink">{flat.slice(at, end)}</mark>
      {flat.slice(end)}
    </>
  )
}

export function Citations({ citations }: { citations: Citation[] }) {
  const [opened, setOpened] = useState<Opened | null>(null)

  if (!citations.length) return <p className="text-sm text-ink/55">No verified citation survived the guardrails for this item.</p>

  const open = (id: string) => {
    if (opened?.id === id) return setOpened(null)
    setOpened({ id, state: 'loading' })
    fetchRegulation(id)
      .then((chunk) => setOpened({ id, state: 'ready', chunk }))
      .catch((e: Error) => setOpened({ id, state: 'error', message: e.message }))
  }

  return (
    <ul className="space-y-3">
      {citations.map((c) => (
        <li key={`${c.regulation_id}:${c.quote}`}>
          <button
            type="button"
            title={c.quote}
            onClick={() => open(c.regulation_id)}
            aria-expanded={opened?.id === c.regulation_id}
            className="group w-full rounded-md border border-ink/10 bg-white px-4 py-3 text-left transition hover:border-ink/30"
          >
            <span className="font-mono text-xs text-accent">{c.regulation_id}</span>
            <span className="mt-1 block font-display text-[15px] leading-snug text-ink/85 italic">“{c.quote}”</span>
          </button>
          {opened?.id === c.regulation_id && (
            <div className="mt-1 rounded-md border border-ink/10 bg-white/70 px-4 py-3 text-sm">
              {opened.state === 'loading' && <p className="text-ink/50">Loading clause…</p>}
              {opened.state === 'error' && <p className="text-against">{opened.message}</p>}
              {opened.state === 'ready' && (
                <>
                  <p className="font-semibold">
                    {opened.chunk.citation}
                    {opened.chunk.heading && <span className="font-normal text-ink/60"> — {opened.chunk.heading}</span>}
                  </p>
                  <p className="mt-2 max-h-72 overflow-auto leading-relaxed text-ink/80">
                    <Highlighted text={opened.chunk.text} quote={c.quote} />
                  </p>
                  <p className="mt-2 text-xs text-ink/50">
                    As of {opened.chunk.as_of} ·{' '}
                    <a href={opened.chunk.source_url} target="_blank" rel="noreferrer" className="underline">
                      official source
                    </a>
                    {opened.chunk.notes && ` · ${opened.chunk.notes}`}
                  </p>
                </>
              )}
            </div>
          )}
        </li>
      ))}
    </ul>
  )
}
