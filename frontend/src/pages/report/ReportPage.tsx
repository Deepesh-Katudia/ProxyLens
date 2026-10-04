import { useCallback, useEffect, useState } from 'react'
import { ConfidenceBar, RecommendationBadge, TypeChip } from '../../components/Badges'
import { recommendationLabel } from '../../lib/labels'
import { fetchReport } from '../../lib/api'
import { Link } from '../../lib/router'
import { RECOMMENDATIONS, type DocumentReport, type ReportItem } from '../../lib/types'
import { JobProgress } from '../upload/JobProgress'
import { useJob } from '../upload/useJob'
import { Drawer } from './Drawer'

function Summary({ items }: { items: ReportItem[] }) {
  const counts = RECOMMENDATIONS.map((r) => [r, items.filter((i) => i.analysis?.recommendation === r).length] as const)
  return (
    <dl className="grid grid-cols-2 gap-px overflow-hidden rounded-lg border border-ink/10 bg-ink/10 sm:grid-cols-4">
      {counts.map(([rec, n]) => (
        <div key={rec} className="bg-white px-4 py-3">
          <dt className="text-xs uppercase tracking-wider text-ink/50">{recommendationLabel(rec)}</dt>
          <dd className="font-display text-3xl font-semibold">{n}</dd>
        </div>
      ))}
    </dl>
  )
}

function lawFailures(item: ReportItem): number {
  return item.analysis?.rule_findings.filter((f) => f.kind === 'LAW' && f.status === 'FAIL').length ?? 0
}

export function ReportPage({ documentId }: { documentId: string }) {
  const [report, setReport] = useState<DocumentReport | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [openId, setOpenId] = useState<string | null>(null)
  const pending = report?.job && report.job.status !== 'done' && report.job.status !== 'failed'
  const { job } = useJob(pending ? report.job!.id : null)

  const load = useCallback(() => {
    fetchReport(documentId)
      .then(setReport)
      .catch((e: Error) => setError(e.message))
  }, [documentId])

  useEffect(load, [load])
  useEffect(() => {
    if (pending && job?.status === 'done') load()
  }, [pending, job?.status, load])

  if (error) return <p className="text-against">Could not load the report: {error}</p>
  if (!report) return <p className="text-ink/50">Loading report…</p>

  const { document: doc, items } = report
  const open = items.find((i) => i.resolution.id === openId) ?? null

  return (
    <div>
      <Link to="/" className="text-sm text-ink/55 hover:text-ink">
        ← New analysis
      </Link>
      <header className="mt-3 mb-8 flex flex-wrap items-end justify-between gap-4 border-b border-ink/15 pb-6">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.2em] text-ink/50">
            {doc.meeting_type ?? 'Notice'} · {doc.pages ?? '?'} pages · {doc.filename}
          </p>
          <h1 className="mt-1 font-display text-4xl font-semibold tracking-tight">{doc.company ?? 'Unknown company'}</h1>
        </div>
        <p className="text-sm text-ink/55">Analysed {new Date(doc.uploaded_at).toLocaleString()}</p>
      </header>

      {pending && job && <JobProgress job={job} />}
      {report.job?.status === 'failed' && <JobProgress job={report.job} />}

      {items.length > 0 && (
        <>
          <Summary items={items} />
          <div className="mt-6 overflow-x-auto rounded-lg border border-ink/10 bg-white">
            <table className="w-full text-left text-sm">
              <thead className="border-b border-ink/10 text-xs uppercase tracking-wider text-ink/50">
                <tr>
                  <th className="w-14 px-4 py-3 font-medium">Item</th>
                  <th className="px-4 py-3 font-medium">Resolution</th>
                  <th className="px-4 py-3 font-medium">Type</th>
                  <th className="px-4 py-3 font-medium">Vote</th>
                  <th className="px-4 py-3 font-medium">Confidence</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-ink/[0.07]">
                {items.map((item) => {
                  const a = item.analysis
                  const fails = lawFailures(item)
                  return (
                    <tr
                      key={item.resolution.id}
                      onClick={() => setOpenId(item.resolution.id)}
                      className={`cursor-pointer transition-colors hover:bg-paper ${openId === item.resolution.id ? 'bg-paper' : ''}`}
                    >
                      <td className="px-4 py-3 font-display text-lg text-ink/45">{item.resolution.item_no}</td>
                      <td className="px-4 py-3">
                        <button type="button" className="text-left font-medium hover:underline focus:underline focus:outline-none">
                          {item.resolution.extracted?.title ?? item.resolution.raw_text.slice(0, 90)}
                        </button>
                        <div className="mt-0.5 flex flex-wrap gap-2 text-xs text-ink/50">
                          {item.resolution.extracted?.is_special_resolution && <span>Special resolution</span>}
                          {fails > 0 && <span className="font-semibold text-against">{fails} LAW rule failed</span>}
                          {item.feedback.length > 0 && (
                            <span className="font-semibold text-ink">
                              Analyst: {recommendationLabel(item.feedback[item.feedback.length - 1].analyst_recommendation)}
                            </span>
                          )}
                        </div>
                      </td>
                      <td className="px-4 py-3">
                        <TypeChip value={item.resolution.extracted?.resolution_type} />
                      </td>
                      <td className="px-4 py-3">{a ? <RecommendationBadge value={a.recommendation} /> : '—'}</td>
                      <td className="px-4 py-3">{a ? <ConfidenceBar value={a.confidence} /> : '—'}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </>
      )}
      {open && <Drawer item={open} onClose={() => setOpenId(null)} onSaved={load} />}
    </div>
  )
}
