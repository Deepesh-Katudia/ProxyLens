import { useEffect, useState } from 'react'
import { ApiError, fetchLatestEval } from '../lib/api'
import { Confusion } from './eval/Confusion'
import type { EvalMetrics, EvalProvider, EvalSummary } from './eval/types'

type State = { kind: 'loading' } | { kind: 'empty' } | { kind: 'error'; message: string } | { kind: 'ready'; run: EvalSummary }

const COLUMNS: { key: keyof EvalMetrics; label: string }[] = [
  { key: 'json_valid', label: 'JSON valid' },
  { key: 'type_accuracy', label: 'Type acc.' },
  { key: 'type_macro_f1', label: 'Type macro-F1' },
  { key: 'persons_f1', label: 'Persons F1' },
  { key: 'amounts_f1', label: 'Amounts F1' },
  { key: 'special_f1', label: 'Special F1' },
  { key: 'fallback_rate', label: 'Fallback' },
]

const pct = (v: number | null | undefined) => (v === null || v === undefined ? '—' : `${(100 * v).toFixed(1)}%`)

function Bars({ providers, pick, unit, format }: { providers: EvalProvider[]; pick: (m: EvalMetrics) => number | null; unit: string; format: (v: number) => string }) {
  const values = providers.map((p) => pick(p.metrics))
  const peak = Math.max(1e-9, ...values.map((v) => v ?? 0))
  return (
    <ul className="space-y-2">
      {providers.map((p, i) => {
        const v = values[i]
        return (
          <li key={p.run_id} className="grid grid-cols-[12rem_1fr_5rem] items-center gap-3 text-sm">
            <span className="truncate text-ink/70" title={p.name}>{p.name}</span>
            <span className="h-2 rounded-full bg-ink/[0.06]">
              {v !== null && <span className="block h-full rounded-full bg-ink/70" style={{ width: `${(100 * v) / peak}%` }} />}
            </span>
            <span className="text-right">{v === null ? '—' : `${format(v)}${unit}`}</span>
          </li>
        )
      })}
    </ul>
  )
}

function Report({ run }: { run: EvalSummary }) {
  const [selected, setSelected] = useState(run.providers[0]?.run_id)
  const current = run.providers.find((p) => p.run_id === selected) ?? run.providers[0]
  const humanGold = run.reference.kind === 'human'
  return (
    <>
      <div className={`mt-8 rounded-lg border px-5 py-4 ${humanGold ? 'border-accent/30 bg-accent/5' : 'border-review/50 bg-review/10'}`}>
        <p className="text-xs font-semibold uppercase tracking-wider text-ink/55">Reference labels</p>
        <p className="mt-1 text-sm leading-relaxed">{run.reference.description}</p>
        {!humanGold && <p className="mt-1 text-sm text-ink/65">Scores show agreement with that reference, not accuracy against human judgement.</p>}
      </div>

      <div className="mt-8 overflow-x-auto rounded-lg border border-ink/10 bg-white">
        <table className="w-full text-sm">
          <thead className="border-b border-ink/10 text-left text-xs uppercase tracking-wider text-ink/50">
            <tr>
              <th className="px-4 py-3 font-medium">Model</th>
              <th className="px-3 py-3 font-medium">n</th>
              {COLUMNS.map((c) => (
                <th key={c.key} className="px-3 py-3 text-right font-medium">{c.label}</th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-ink/[0.07]">
            {run.providers.map((p) => (
              <tr key={p.run_id} onClick={() => setSelected(p.run_id)} className={`cursor-pointer hover:bg-paper ${p.run_id === current?.run_id ? 'bg-paper' : ''}`}>
                <td className="px-4 py-3">
                  <p className="font-medium">{p.name}</p>
                  <p className="text-xs text-ink/45">{p.hardware}</p>
                </td>
                <td className="px-3 py-3 text-ink/60">{p.n}</td>
                {COLUMNS.map((c) => (
                  <td key={c.key} className="px-3 py-3 text-right">{pct(p.metrics[c.key] as number | null)}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="mt-10 grid gap-10 lg:grid-cols-[1fr_22rem]">
        {current && (
          <section aria-labelledby="confusion-heading">
            <h2 id="confusion-heading" className="mb-1 text-xs font-semibold uppercase tracking-[0.16em] text-ink/50">Confusion matrix</h2>
            <p className="mb-4 text-sm text-ink/60">{current.name} · click a row in the table to switch</p>
            <Confusion matrix={current.confusion} />
          </section>
        )}
        <section className="space-y-8">
          <div>
            <h2 className="mb-3 text-xs font-semibold uppercase tracking-[0.16em] text-ink/50">Latency p50 per resolution</h2>
            <Bars providers={run.providers} pick={(m) => (m.latency_p50_ms === null ? null : m.latency_p50_ms / 1000)} unit=" s" format={(v) => v.toFixed(1)} />
          </div>
          <div>
            <h2 className="mb-3 text-xs font-semibold uppercase tracking-[0.16em] text-ink/50">Cost per 1,000 resolutions</h2>
            <Bars providers={run.providers} pick={(m) => m.cost_per_1k_usd} unit="" format={(v) => `$${v.toFixed(2)}`} />
            <p className="mt-2 text-xs text-ink/50">API rows use real token usage; CPU rows estimate Cloud Run cost from local latency.</p>
          </div>
          {run.citation_precision?.precision != null && (
            <p className="text-sm text-ink/70">
              Citation precision before guardrails: <span className="font-semibold">{pct(run.citation_precision.precision)}</span> over{' '}
              {run.citation_precision.analyses} analyses.
            </p>
          )}
        </section>
      </div>
      <p className="mt-10 text-xs text-ink/45">Report {run.run_id} · generated {new Date(run.created_at).toLocaleString()}</p>
    </>
  )
}

export function EvalPage() {
  const [state, setState] = useState<State>({ kind: 'loading' })

  useEffect(() => {
    fetchLatestEval()
      .then((run) => setState({ kind: 'ready', run: run as unknown as EvalSummary }))
      .catch((e: Error) => setState(e instanceof ApiError && e.status === 404 ? { kind: 'empty' } : { kind: 'error', message: e.message }))
  }, [])

  return (
    <div>
      <p className="text-xs font-semibold uppercase tracking-[0.2em] text-accent">Evaluation</p>
      <h1 className="mt-2 font-display text-4xl font-semibold tracking-tight">Base vs fine-tuned vs teacher</h1>
      <p className="mt-3 max-w-2xl text-ink/70">
        Every model is scored the same way on company-held-out notices. Invalid JSON counts as a wrong answer. Nothing on
        this page is estimated except where it says so.
      </p>
      {state.kind === 'loading' && <p className="mt-10 text-ink/50">Loading…</p>}
      {state.kind === 'error' && <p className="mt-10 text-against">{state.message}</p>}
      {state.kind === 'empty' && (
        <p className="mt-10 rounded-lg border border-dashed border-ink/25 bg-white p-6 text-ink/65">
          No evaluation run yet. Run <code className="font-mono">python -m eval.report --db</code> after collecting predictions.
        </p>
      )}
      {state.kind === 'ready' && <Report run={state.run} />}
    </div>
  )
}
