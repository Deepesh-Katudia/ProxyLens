import { useCallback, useEffect, useState } from 'react'
import { ExtractionForm } from './ExtractionForm'
import { type Extraction, type GoldItem, type GoldProgress, blankExtraction, fetchItem, fetchProgress, saveLabel } from './api'
import { inputClass } from './styles'

const KEY_STORAGE = 'proxylens.apiKey'
const LABELLER_STORAGE = 'proxylens.labeller'

function stored(key: string): string {
  try {
    return localStorage.getItem(key) ?? ''
  } catch {
    return ''
  }
}

function remember(key: string, value: string) {
  try {
    localStorage.setItem(key, value)
  } catch {
    // Storage can be unavailable (private mode); the value just isn't remembered.
  }
}

function cleaned(extraction: Extraction): Extraction {
  return { ...extraction, key_facts: extraction.key_facts.map((f) => f.trim()).filter(Boolean) }
}

export function LabelPage() {
  const [progress, setProgress] = useState<GoldProgress | null>(null)
  const [item, setItem] = useState<GoldItem | null>(null)
  const [draft, setDraft] = useState<Extraction | null>(null)
  const [skipReason, setSkipReason] = useState('')
  const [apiKey, setApiKey] = useState(() => stored(KEY_STORAGE))
  const [labeller, setLabeller] = useState(() => stored(LABELLER_STORAGE))
  const [message, setMessage] = useState<{ kind: 'ok' | 'error'; text: string } | null>(null)

  const refresh = useCallback(() => {
    fetchProgress()
      .then(setProgress)
      .catch((e: Error) => setMessage({ kind: 'error', text: e.message }))
  }, [])

  useEffect(refresh, [refresh])

  const open = useCallback((itemId: string) => {
    setMessage(null)
    fetchItem(itemId)
      .then((loaded) => {
        setItem(loaded)
        setDraft(loaded.label?.extraction ?? blankExtraction(loaded))
        setSkipReason(loaded.label?.skip_reason ?? '')
      })
      .catch((e: Error) => setMessage({ kind: 'error', text: e.message }))
  }, [])

  const next = () => {
    const pending = progress?.items.find((i) => i.status === null && i.item_id !== item?.item_id)
    if (pending) open(pending.item_id)
  }

  const submit = async (status: 'labelled' | 'skipped') => {
    if (!item || !draft) return
    if (status === 'skipped' && !skipReason.trim()) {
      setMessage({ kind: 'error', text: 'Say why the item is skipped.' })
      return
    }
    try {
      await saveLabel(
        item.item_id,
        {
          status,
          extraction: status === 'labelled' ? cleaned(draft) : null,
          skip_reason: status === 'skipped' ? skipReason.trim() : null,
          labeller,
        },
        apiKey,
      )
      setMessage({ kind: 'ok', text: status === 'labelled' ? 'Saved.' : 'Skipped.' })
      refresh()
    } catch (e) {
      setMessage({ kind: 'error', text: (e as Error).message })
    }
  }

  const done = progress ? progress.labelled + progress.skipped : 0

  return (
    <div className="flex h-screen flex-col">
      <header className="flex flex-wrap items-center gap-4 border-b border-ink/10 bg-white px-4 py-3">
        <a href="/" className="text-lg font-semibold tracking-tight">
          ProxyLens <span className="font-normal text-ink/50">/ gold labels</span>
        </a>
        {progress && (
          <div className="flex items-center gap-2 text-sm text-ink/70">
            <div className="h-2 w-40 overflow-hidden rounded-full bg-ink/10">
              <div className="h-full bg-accent" style={{ width: `${(100 * done) / Math.max(progress.total, 1)}%` }} />
            </div>
            {progress.labelled} labelled · {progress.skipped} skipped · {progress.total} total
          </div>
        )}
        <div className="ml-auto flex gap-2">
          <input
            className={`${inputClass} w-36`}
            placeholder="Your name"
            value={labeller}
            onChange={(e) => {
              setLabeller(e.target.value)
              remember(LABELLER_STORAGE, e.target.value)
            }}
          />
          <input
            className={`${inputClass} w-44`}
            type="password"
            placeholder="API key"
            value={apiKey}
            onChange={(e) => {
              setApiKey(e.target.value)
              remember(KEY_STORAGE, e.target.value)
            }}
          />
        </div>
      </header>

      <div className="grid min-h-0 flex-1 grid-cols-1 lg:grid-cols-[18rem_1fr_28rem]">
        <nav className="min-h-0 overflow-y-auto border-r border-ink/10 bg-white">
          {progress?.items.map((i) => (
            <button
              key={i.item_id}
              type="button"
              onClick={() => open(i.item_id)}
              className={`block w-full border-b border-ink/5 px-3 py-2 text-left text-xs hover:bg-paper ${
                item?.item_id === i.item_id ? 'bg-accent/10' : ''
              }`}
            >
              <span className="flex items-center justify-between gap-2 font-medium">
                <span className="truncate">{i.company}</span>
                <span className={i.status === 'labelled' ? 'text-accent' : i.status === 'skipped' ? 'text-amber-700' : 'text-ink/30'}>
                  {i.status === 'labelled' ? '●' : i.status === 'skipped' ? '◐' : '○'} #{i.item_no}
                </span>
              </span>
              <span className="line-clamp-2 text-ink/60">{i.preview}</span>
            </button>
          ))}
        </nav>

        <main className="min-h-0 overflow-y-auto px-6 py-5">
          {item ? (
            <article className="mx-auto flex max-w-3xl flex-col gap-6">
              <div className="text-sm text-ink/60">
                {item.company} · item {item.item_no} · {item.section ?? 'section not stated'} · {item.file}
              </div>
              <section>
                <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-ink/50">Agenda item</h2>
                <pre className="whitespace-pre-wrap font-sans text-sm leading-relaxed">{item.text}</pre>
              </section>
              <section>
                <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-ink/50">Explanatory statement</h2>
                <pre className="whitespace-pre-wrap font-sans text-sm leading-relaxed text-ink/85">
                  {item.explanatory_statement ?? 'None for this item.'}
                </pre>
              </section>
            </article>
          ) : (
            <p className="mt-20 text-center text-ink/50">Pick an item on the left to start labelling.</p>
          )}
        </main>

        <aside className="min-h-0 overflow-y-auto border-l border-ink/10 bg-white px-5 py-5">
          {item && draft ? (
            <div className="flex flex-col gap-5">
              <ExtractionForm value={draft} onChange={setDraft} />
              <div className="flex flex-col gap-2 border-t border-ink/10 pt-4">
                <div className="flex gap-2">
                  <button type="button" onClick={() => submit('labelled')} className="rounded-md bg-accent px-4 py-2 text-sm font-medium text-white hover:brightness-110">
                    Save label
                  </button>
                  <button type="button" onClick={next} className="rounded-md border border-ink/15 px-4 py-2 text-sm hover:bg-paper">
                    Next unlabelled →
                  </button>
                </div>
                <div className="flex gap-2">
                  <input className={inputClass} placeholder="Skip reason (e.g. not a resolution)" value={skipReason} onChange={(e) => setSkipReason(e.target.value)} />
                  <button type="button" onClick={() => submit('skipped')} className="shrink-0 rounded-md border border-amber-600/40 px-3 text-sm text-amber-800 hover:bg-amber-50">
                    Skip
                  </button>
                </div>
                {message && <p className={`text-sm ${message.kind === 'ok' ? 'text-accent' : 'text-red-700'}`}>{message.text}</p>}
              </div>
            </div>
          ) : (
            message && <p className="text-sm text-red-700">{message.text}</p>
          )}
        </aside>
      </div>
    </div>
  )
}
