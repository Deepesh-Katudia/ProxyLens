import { useEffect, useState } from 'react'
import { ApiError, fetchLatestEval } from '../lib/api'

type State = { kind: 'loading' } | { kind: 'empty' } | { kind: 'error'; message: string } | { kind: 'ready'; run: Record<string, unknown> }

const PLANNED = [
  ['JSON validity', 'Outputs that parse and validate before any repair'],
  ['Type accuracy · macro-F1', 'resolution_type against hand-labelled gold, with a confusion matrix'],
  ['Field-level F1', 'Persons, amounts (±1%), special resolution, counterparty'],
  ['Citation precision', 'Citations passing the retrieved-id and verbatim-quote check'],
  ['Fallback rate', 'Items where the student failed and the teacher answered'],
  ['Latency · cost', 'p50/p95 per resolution and cost per 1,000 resolutions'],
] as const

function flatten(value: unknown, prefix = ''): [string, string][] {
  if (value && typeof value === 'object' && !Array.isArray(value)) {
    return Object.entries(value as Record<string, unknown>).flatMap(([k, v]) => flatten(v, prefix ? `${prefix}.${k}` : k))
  }
  if (Array.isArray(value)) return [[prefix, `${value.length} entries`]]
  return [[prefix, typeof value === 'number' ? String(Math.round(value * 1000) / 1000) : String(value)]]
}

export function EvalPage() {
  const [state, setState] = useState<State>({ kind: 'loading' })

  useEffect(() => {
    fetchLatestEval()
      .then((run) => setState({ kind: 'ready', run }))
      .catch((e: Error) => setState(e instanceof ApiError && e.status === 404 ? { kind: 'empty' } : { kind: 'error', message: e.message }))
  }, [])

  return (
    <div className="max-w-4xl">
      <p className="text-xs font-semibold uppercase tracking-[0.2em] text-accent">Evaluation</p>
      <h1 className="mt-2 font-display text-4xl font-semibold tracking-tight">Base 3B vs fine-tuned 3B vs teacher</h1>
      <p className="mt-3 max-w-2xl text-ink/70">
        Every provider is scored the same way on a company-held-out gold set labelled by hand. Numbers appear here only
        once a real run exists; nothing on this page is estimated.
      </p>

      {state.kind === 'loading' && <p className="mt-10 text-ink/50">Loading…</p>}
      {state.kind === 'error' && <p className="mt-10 text-against">{state.message}</p>}
      {state.kind === 'empty' && (
        <div className="mt-10 rounded-lg border border-dashed border-ink/25 bg-white p-6">
          <p className="font-display text-xl">No evaluation run yet</p>
          <p className="mt-1 text-sm text-ink/65">The harness (Phase 7) will report:</p>
          <dl className="mt-5 grid gap-x-8 gap-y-4 sm:grid-cols-2">
            {PLANNED.map(([name, text]) => (
              <div key={name} className="border-t border-ink/10 pt-2">
                <dt className="text-sm font-semibold">{name}</dt>
                <dd className="text-sm text-ink/60">{text}</dd>
              </div>
            ))}
          </dl>
        </div>
      )}
      {state.kind === 'ready' && (
        <dl className="mt-10 divide-y divide-ink/10 rounded-lg border border-ink/10 bg-white">
          {flatten(state.run)
            .filter(([k]) => k !== 'id')
            .map(([k, v]) => (
              <div key={k} className="grid grid-cols-[1fr_auto] gap-4 px-4 py-2 text-sm">
                <dt className="font-mono text-ink/65">{k}</dt>
                <dd>{v}</dd>
              </div>
            ))}
        </dl>
      )}
    </div>
  )
}
