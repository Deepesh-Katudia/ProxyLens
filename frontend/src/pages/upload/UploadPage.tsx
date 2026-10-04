import { useEffect, useRef, useState, type DragEvent } from 'react'
import { ApiError, fetchDocuments, uploadNotice } from '../../lib/api'
import { ApiKeyField } from '../../components/ApiKeyField'
import { useApiKey } from '../../lib/useApiKey'
import { navigate } from '../../lib/navigation'
import { Link } from '../../lib/router'
import type { DocumentMeta } from '../../lib/types'
import { JobProgress } from './JobProgress'
import { useJob } from './useJob'

const STEPS = [
  ['Extract', 'A fine-tuned 3B model turns every agenda item into structured JSON.'],
  ['Retrieve', 'SEBI LODR and Companies Act clauses come back from Atlas Vector Search.'],
  ['Check', 'Deterministic LAW and POLICY rules run before any LLM reasoning.'],
  ['Recommend', 'A vote with cited clauses; anything uncertain goes to review.'],
] as const

function parseCrore(value: string): number | undefined {
  const n = Number(value.replace(/,/g, ''))
  return value.trim() && Number.isFinite(n) && n >= 0 ? n : undefined
}

function RecentReports() {
  const [docs, setDocs] = useState<DocumentMeta[] | null>(null)
  useEffect(() => {
    fetchDocuments().then(setDocs).catch(() => setDocs([]))
  }, [])
  if (!docs?.length) return null
  return (
    <section aria-labelledby="recent-heading" className="mt-14">
      <h2 id="recent-heading" className="mb-3 text-xs font-semibold uppercase tracking-[0.18em] text-ink/50">
        Recent reports
      </h2>
      <ul className="divide-y divide-ink/10 border-y border-ink/10">
        {docs.map((d) => (
          <li key={d.id}>
            <Link to={`/documents/${d.id}`} className="flex items-baseline justify-between gap-4 py-3 hover:bg-ink/[0.03]">
              <span className="truncate font-medium">{d.company ?? d.filename}</span>
              <span className="shrink-0 text-sm text-ink/55">
                {d.meeting_type ?? '—'} · {d.item_count ?? '?'} items · {new Date(d.uploaded_at).toLocaleDateString()}
              </span>
            </Link>
          </li>
        ))}
      </ul>
    </section>
  )
}

export function UploadPage() {
  const [apiKey, setApiKey] = useApiKey()
  const [file, setFile] = useState<File | null>(null)
  const [dragging, setDragging] = useState(false)
  const [turnover, setTurnover] = useState('')
  const [profit, setProfit] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [upload, setUpload] = useState<{ documentId: string; jobId: string } | null>(null)
  const input = useRef<HTMLInputElement>(null)
  const { job, error: pollError } = useJob(upload?.jobId ?? null)

  useEffect(() => {
    if (job?.status === 'done' && upload) navigate(`/documents/${upload.documentId}`)
  }, [job?.status, upload])

  const pick = (candidate: File | undefined) => {
    setError(null)
    if (!candidate) return
    if (!candidate.name.toLowerCase().endsWith('.pdf')) return setError('Choose a PDF notice.')
    setFile(candidate)
  }

  const onDrop = (e: DragEvent) => {
    e.preventDefault()
    setDragging(false)
    pick(e.dataTransfer.files[0])
  }

  const submit = async () => {
    if (!file) return
    if (!apiKey) return setError('Enter the API key first (API_KEY in the server .env).')
    setBusy(true)
    setError(null)
    try {
      const res = await uploadNotice(file, apiKey, parseCrore(turnover), parseCrore(profit))
      setUpload({ documentId: res.document_id, jobId: res.job_id })
    } catch (e) {
      setError(e instanceof ApiError && e.status === 401 ? 'The API key was rejected.' : (e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div>
      <section aria-labelledby="hero-heading" className="grid gap-10 lg:grid-cols-[1.1fr_1fr] lg:items-start">
        <div className="pt-2">
          <p className="mb-4 text-xs font-semibold uppercase tracking-[0.2em] text-accent">Proxy voting, first pass</p>
          <h1 id="hero-heading" className="font-display text-4xl leading-[1.08] font-semibold tracking-tight sm:text-5xl">
            Drop an AGM notice.
            <br />
            Get a vote memo with the law cited.
          </h1>
          <ol className="mt-8 grid gap-4 sm:grid-cols-2">
            {STEPS.map(([title, text], i) => (
              <li key={title} className="border-t border-ink/15 pt-3">
                <p className="text-sm font-semibold">
                  <span className="mr-2 font-display text-ink/40">{i + 1}</span>
                  {title}
                </p>
                <p className="mt-1 text-sm leading-relaxed text-ink/65">{text}</p>
              </li>
            ))}
          </ol>
        </div>

        <div className="flex flex-col gap-4">
          {upload && job ? (
            <JobProgress job={job} />
          ) : (
            <button
              type="button"
              onClick={() => input.current?.click()}
              onDragOver={(e) => {
                e.preventDefault()
                setDragging(true)
              }}
              onDragLeave={() => setDragging(false)}
              onDrop={onDrop}
              className={`flex min-h-56 flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed px-6 text-center transition-colors focus:outline-none focus-visible:ring-4 focus-visible:ring-accent/25 ${
                dragging ? 'border-accent bg-accent/5' : 'border-ink/20 bg-white hover:border-ink/40'
              }`}
            >
              <span className="font-display text-xl">{file ? file.name : 'Drop the notice PDF here'}</span>
              <span className="text-sm text-ink/55">
                {file ? `${(file.size / 1_000_000).toFixed(1)} MB · click to change` : 'or click to choose · text-based PDFs, up to 25 MB'}
              </span>
              <input ref={input} type="file" accept="application/pdf,.pdf" className="hidden" onChange={(e) => pick(e.target.files?.[0])} />
            </button>
          )}

          {!upload && (
            <>
              <details className="rounded-lg border border-ink/10 bg-white px-4 py-3 text-sm">
                <summary className="cursor-pointer text-ink/70">Company figures (optional, improves two LAW checks)</summary>
                <div className="mt-3 grid grid-cols-2 gap-3">
                  <label className="text-xs text-ink/60">
                    Consolidated turnover (₹ crore)
                    <input className="mt-1 w-full rounded border border-ink/15 px-2 py-1.5 text-sm" inputMode="decimal" value={turnover} onChange={(e) => setTurnover(e.target.value)} />
                  </label>
                  <label className="text-xs text-ink/60">
                    Net profit, s.198 (₹ crore)
                    <input className="mt-1 w-full rounded border border-ink/15 px-2 py-1.5 text-sm" inputMode="decimal" value={profit} onChange={(e) => setProfit(e.target.value)} />
                  </label>
                </div>
                <p className="mt-2 text-xs text-ink/50">Used for RPT materiality (Schedule XII) and promoter pay (Reg 17(6)(e)).</p>
              </details>
              <div className="flex flex-wrap items-center justify-between gap-3">
                <ApiKeyField value={apiKey} onChange={setApiKey} />
                <button
                  type="button"
                  disabled={!file || busy}
                  onClick={submit}
                  className="rounded-md bg-ink px-5 py-2.5 text-sm font-semibold text-paper transition hover:bg-ink/85 active:translate-y-px disabled:cursor-not-allowed disabled:opacity-40"
                >
                  {busy ? 'Uploading…' : 'Analyse notice'}
                </button>
              </div>
            </>
          )}
          {(error || pollError) && <p className="text-sm text-against">{error ?? pollError}</p>}
          {job?.status === 'failed' && (
            <button type="button" className="self-start text-sm underline" onClick={() => setUpload(null)}>
              Try another file
            </button>
          )}
        </div>
      </section>
      <RecentReports />
    </div>
  )
}
