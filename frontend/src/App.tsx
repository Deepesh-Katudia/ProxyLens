import { useEffect, useState } from 'react'

type Health = {
  status: 'ok' | 'degraded'
  db: 'ok' | 'unreachable' | 'not_configured'
  model: 'loaded' | 'not_loaded'
}

type HealthState = { kind: 'loading' } | { kind: 'ready'; health: Health } | { kind: 'error'; message: string }

function useHealth(): HealthState {
  const [state, setState] = useState<HealthState>({ kind: 'loading' })

  useEffect(() => {
    const controller = new AbortController()
    fetch('/api/v1/healthz', { signal: controller.signal })
      .then(async (res) => setState({ kind: 'ready', health: (await res.json()) as Health }))
      .catch((err: unknown) => {
        if (controller.signal.aborted) return
        setState({ kind: 'error', message: err instanceof Error ? err.message : 'API unreachable' })
      })
    return () => controller.abort()
  }, [])

  return state
}

function StatusPill({ state }: { state: HealthState }) {
  if (state.kind === 'loading') return <span className="text-sm text-ink/60">Checking API…</span>
  if (state.kind === 'error') return <span className="text-sm text-red-700">API unreachable</span>
  const ok = state.health.status === 'ok'
  return (
    <span
      className={`rounded-full px-3 py-1 text-sm font-medium ${ok ? 'bg-accent/15 text-accent' : 'bg-amber-100 text-amber-800'}`}
    >
      API {state.health.status} · DB {state.health.db}
    </span>
  )
}

export default function App() {
  const health = useHealth()

  return (
    <main className="mx-auto flex min-h-screen max-w-3xl flex-col gap-8 px-4 py-16">
      <header className="flex flex-wrap items-center justify-between gap-4">
        <h1 className="text-4xl font-semibold tracking-tight">ProxyLens</h1>
        <StatusPill state={health} />
      </header>
      <p className="text-lg text-ink/80">
        AI proxy-voting analyst for Indian AGM/EGM resolutions: extract each resolution, check it against SEBI LODR and
        the Companies Act 2013, and recommend a vote with cited clauses.
      </p>
      <p className="rounded-md border border-ink/10 bg-white px-4 py-3 text-sm text-ink/70">
        Research and educational tool. Not investment or voting advice.
      </p>
    </main>
  )
}
