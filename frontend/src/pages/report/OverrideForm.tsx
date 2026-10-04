import { useState } from 'react'
import { RecommendationBadge } from '../../components/Badges'
import { recommendationLabel } from '../../lib/labels'
import { ApiError, submitFeedback } from '../../lib/api'
import { ApiKeyField } from '../../components/ApiKeyField'
import { useApiKey } from '../../lib/useApiKey'
import { RECOMMENDATIONS, type Feedback, type Recommendation } from '../../lib/types'

export function OverrideForm({ analysisId, feedback, onSaved }: { analysisId: string; feedback: Feedback[]; onSaved: () => void }) {
  const [apiKey, setApiKey] = useApiKey()
  const [recommendation, setRecommendation] = useState<Recommendation>('AGAINST')
  const [reason, setReason] = useState('')
  const [state, setState] = useState<{ kind: 'idle' | 'saving' | 'saved' } | { kind: 'error'; message: string }>({ kind: 'idle' })

  const submit = async () => {
    if (reason.trim().length < 3) return setState({ kind: 'error', message: 'Give a short reason.' })
    if (!apiKey) return setState({ kind: 'error', message: 'Enter the API key.' })
    setState({ kind: 'saving' })
    try {
      await submitFeedback(analysisId, recommendation, reason.trim(), apiKey)
      setReason('')
      setState({ kind: 'saved' })
      onSaved()
    } catch (e) {
      const message = e instanceof ApiError && e.status === 401 ? 'The API key was rejected.' : (e as Error).message
      setState({ kind: 'error', message })
    }
  }

  return (
    <div className="space-y-4">
      {feedback.length > 0 && (
        <ul className="space-y-2">
          {feedback.map((f) => (
            <li key={f.id} className="rounded-md border border-ink/10 bg-white px-3 py-2 text-sm">
              <div className="flex items-center justify-between gap-2">
                <RecommendationBadge value={f.analyst_recommendation} />
                <span className="text-xs text-ink/45">{new Date(f.created_at).toLocaleString()}</span>
              </div>
              <p className="mt-1.5 text-ink/80">{f.reason}</p>
            </li>
          ))}
        </ul>
      )}
      <fieldset className="space-y-3">
        <legend className="sr-only">Record an override</legend>
        <div className="flex flex-wrap gap-2" role="radiogroup" aria-label="Analyst recommendation">
          {RECOMMENDATIONS.map((r) => (
            <button
              key={r}
              type="button"
              role="radio"
              aria-checked={recommendation === r}
              onClick={() => setRecommendation(r)}
              className={`rounded border px-3 py-1.5 text-sm transition ${
                recommendation === r ? 'border-ink bg-ink text-paper' : 'border-ink/20 bg-white hover:border-ink/50'
              }`}
            >
              {recommendationLabel(r)}
            </button>
          ))}
        </div>
        <textarea
          rows={3}
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          placeholder="Why? This goes into the feedback set for the next training round."
          className="w-full rounded-md border border-ink/15 bg-white px-3 py-2 text-sm focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/20"
        />
        <div className="flex flex-wrap items-center justify-between gap-3">
          <ApiKeyField value={apiKey} onChange={setApiKey} />
          <button
            type="button"
            onClick={submit}
            disabled={state.kind === 'saving'}
            className="rounded-md bg-ink px-4 py-2 text-sm font-semibold text-paper hover:bg-ink/85 active:translate-y-px disabled:opacity-40"
          >
            {state.kind === 'saving' ? 'Saving…' : 'Save override'}
          </button>
        </div>
        {state.kind === 'saved' && <p className="text-sm text-accent">Saved to feedback.</p>}
        {state.kind === 'error' && <p className="text-sm text-against">{state.message}</p>}
      </fieldset>
    </div>
  )
}
