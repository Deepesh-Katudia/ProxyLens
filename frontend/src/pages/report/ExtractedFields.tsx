import type { Extraction, ExtractorInfo } from '../../lib/types'

const CRORE = 10_000_000

function money(amount: number | null): string {
  if (amount === null) return '—'
  return amount >= CRORE ? `₹${(amount / CRORE).toLocaleString('en-IN', { maximumFractionDigits: 2 })} cr` : `₹${amount.toLocaleString('en-IN')}`
}

const yesNo = (v: boolean | null) => (v === null ? '—' : v ? 'Yes' : 'No')
const num = (v: number | null, unit = '') => (v === null ? '—' : `${v}${unit}`)

function Row({ label, value }: { label: string; value: string | null }) {
  if (value === null || value === '') return null
  return (
    <div className="grid grid-cols-[9rem_1fr] gap-2 py-1 text-sm">
      <dt className="text-ink/55">{label}</dt>
      <dd>{value}</dd>
    </div>
  )
}

export function ExtractedFields({ extraction: e, extractor }: { extraction: Extraction; extractor: ExtractorInfo | null }) {
  return (
    <div className="space-y-4">
      <dl>
        <Row label="Resolution" value={e.is_special_resolution ? 'Special' : 'Ordinary'} />
        <Row label="Counterparty" value={e.counterparty} />
        <Row label="Related party" value={e.counterparty === null && e.counterparty_is_related === null ? null : yesNo(e.counterparty_is_related)} />
        <Row label="Transaction" value={e.transaction_nature} />
        <Row label="Period" value={e.duration_years === null ? null : `${e.duration_years} years`} />
      </dl>

      {e.persons.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-left text-xs text-ink/50">
              <tr>
                <th className="py-1 pr-3 font-medium">Person</th>
                <th className="py-1 pr-3 font-medium">Role</th>
                <th className="py-1 pr-3 font-medium">Age</th>
                <th className="py-1 pr-3 font-medium">Promoter</th>
                <th className="py-1 pr-3 font-medium">Tenure (prior → new)</th>
                <th className="py-1 font-medium">Attendance</th>
              </tr>
            </thead>
            <tbody>
              {e.persons.map((p) => (
                <tr key={`${p.name}-${p.din ?? ''}`} className="border-t border-ink/[0.07]">
                  <td className="py-1.5 pr-3 font-medium">{p.name}</td>
                  <td className="py-1.5 pr-3">{p.role ?? '—'}</td>
                  <td className="py-1.5 pr-3">{num(p.age)}</td>
                  <td className="py-1.5 pr-3">{yesNo(p.is_promoter)}</td>
                  <td className="py-1.5 pr-3">
                    {num(p.prior_tenure_years, 'y')} → {num(p.tenure_years_proposed, 'y')}
                  </td>
                  <td className="py-1.5">{num(p.board_attendance_pct, '%')}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {e.amounts.length > 0 && (
        <ul className="space-y-1 text-sm">
          {e.amounts.map((m, i) => (
            <li key={`${m.raw}-${i}`} className="flex justify-between gap-4">
              <span className="text-ink/65">{m.raw}</span>
              <span className="shrink-0 font-medium">{money(m.amount_inr)}</span>
            </li>
          ))}
        </ul>
      )}

      {e.key_facts.length > 0 && (
        <ul className="list-disc space-y-1 pl-5 text-sm text-ink/80">
          {e.key_facts.map((f) => (
            <li key={f}>{f}</li>
          ))}
        </ul>
      )}

      {extractor && (
        <p className="text-xs text-ink/45">
          Extracted by {extractor.model} in {(extractor.latency_ms / 1000).toFixed(1)} s
          {extractor.used_fallback ? ' · student failed, teacher fallback used' : extractor.valid_first_try ? ' · valid on first try' : ' · repaired once'}
        </p>
      )}
    </div>
  )
}
