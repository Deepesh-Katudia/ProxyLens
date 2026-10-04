import { useEffect, type ReactNode } from 'react'
import { ConfidenceBar, KindTag, RecommendationBadge, RuleStatusMark, TypeChip } from '../../components/Badges'
import type { ReportItem } from '../../lib/types'
import { Citations } from './Citations'
import { ExtractedFields } from './ExtractedFields'
import { OverrideForm } from './OverrideForm'

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="border-t border-ink/10 px-6 py-5">
      <h3 className="mb-3 text-xs font-semibold uppercase tracking-[0.16em] text-ink/50">{title}</h3>
      {children}
    </section>
  )
}

export function Drawer({ item, onClose, onSaved }: { item: ReportItem; onClose: () => void; onSaved: () => void }) {
  const { resolution, analysis } = item
  const extraction = resolution.extracted

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  return (
    <div className="fixed inset-0 z-40 flex justify-end" role="dialog" aria-modal="true" aria-labelledby="drawer-title">
      <button type="button" aria-label="Close" className="absolute inset-0 bg-ink/25" onClick={onClose} />
      <aside className="drawer-in relative flex h-full w-full max-w-2xl flex-col overflow-y-auto bg-paper shadow-2xl">
        <header className="sticky top-0 z-10 border-b border-ink/10 bg-paper/95 px-6 py-5 backdrop-blur">
          <div className="flex items-start justify-between gap-4">
            <div>
              <p className="text-xs uppercase tracking-[0.18em] text-ink/50">Item {resolution.item_no}</p>
              <h2 id="drawer-title" className="mt-1 font-display text-2xl leading-tight font-semibold">
                {extraction?.title ?? 'Could not extract this item'}
              </h2>
            </div>
            <button type="button" onClick={onClose} className="rounded px-2 py-1 text-ink/60 hover:bg-ink/5 hover:text-ink">
              Close ✕
            </button>
          </div>
          {analysis && (
            <div className="mt-4 flex flex-wrap items-center gap-3">
              <RecommendationBadge value={analysis.recommendation} size="lg" />
              <ConfidenceBar value={analysis.confidence} />
              <TypeChip value={extraction?.resolution_type} />
              {analysis.flags.map((f) => (
                <span key={f} className="rounded bg-review/15 px-2 py-0.5 font-mono text-[11px] text-ink/70">
                  {f}
                </span>
              ))}
            </div>
          )}
        </header>

        {analysis && (
          <Section title="Rationale">
            <p className="leading-relaxed">{analysis.rationale}</p>
            {analysis.adjustments.length > 0 && (
              <ul className="mt-4 space-y-1 border-l-2 border-review pl-3 text-sm text-ink/70">
                {analysis.adjustments.map((a) => (
                  <li key={a}>Guardrail: {a}</li>
                ))}
              </ul>
            )}
          </Section>
        )}

        {analysis && analysis.rule_findings.length > 0 && (
          <Section title="Rule checks">
            <ul className="divide-y divide-ink/[0.07]">
              {analysis.rule_findings.map((f) => (
                <li key={f.rule_id} className="grid grid-cols-[auto_1fr_auto] gap-x-3 py-2.5">
                  <KindTag kind={f.kind} />
                  <div>
                    <p className="font-mono text-xs text-ink/70">{f.rule_id}</p>
                    <p className="mt-0.5 text-sm">{f.detail}</p>
                    <p className="mt-0.5 text-xs text-ink/50">
                      {f.source_url ? (
                        <a href={f.source_url} target="_blank" rel="noreferrer" className="underline decoration-ink/30 hover:decoration-ink">
                          {f.citation}
                        </a>
                      ) : (
                        f.citation
                      )}
                      {f.kind === 'LAW' && !f.verified && ' · params not yet re-verified against the amended Act'}
                    </p>
                  </div>
                  <RuleStatusMark status={f.status} />
                </li>
              ))}
            </ul>
          </Section>
        )}

        {analysis && (
          <Section title="Cited regulations">
            <Citations citations={analysis.citations} />
          </Section>
        )}

        {extraction && (
          <Section title="Extracted facts">
            <ExtractedFields extraction={extraction} extractor={resolution.extractor} />
          </Section>
        )}

        <Section title="Notice text">
          <details>
            <summary className="cursor-pointer text-sm text-ink/60">Agenda item and explanatory statement</summary>
            <pre className="mt-3 max-h-96 overflow-auto whitespace-pre-wrap rounded bg-white p-3 font-sans text-xs leading-relaxed text-ink/80">
              {resolution.raw_text}
              {resolution.explanatory_statement && `\n\n— Explanatory statement —\n${resolution.explanatory_statement}`}
            </pre>
          </details>
        </Section>

        {analysis && (
          <Section title="Analyst override">
            <OverrideForm analysisId={analysis.id} feedback={item.feedback} onSaved={onSaved} />
          </Section>
        )}
      </aside>
    </div>
  )
}
