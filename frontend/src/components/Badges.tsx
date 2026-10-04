import { recommendationLabel, typeLabel } from '../lib/labels'
import type { Recommendation, ResolutionType, RuleFinding, RuleStatus } from '../lib/types'

const REC_STYLE: Record<Recommendation, string> = {
  FOR: 'bg-accent text-white',
  AGAINST: 'bg-against text-white',
  ABSTAIN: 'bg-abstain text-white',
  NEEDS_REVIEW: 'bg-review/20 text-[oklch(42%_0.11_70)] ring-1 ring-inset ring-review/50',
}

export function RecommendationBadge({ value, size = 'sm' }: { value: Recommendation; size?: 'sm' | 'lg' }) {
  const scale = size === 'lg' ? 'px-3 py-1 text-sm' : 'px-2 py-0.5 text-xs'
  return (
    <span className={`inline-flex items-center rounded font-semibold uppercase tracking-wide ${scale} ${REC_STYLE[value]}`}>
      {recommendationLabel(value)}
    </span>
  )
}

export function TypeChip({ value }: { value: ResolutionType | null | undefined }) {
  return (
    <span className="inline-block max-w-56 truncate rounded-full border border-ink/12 bg-white px-2 py-0.5 text-xs text-ink/70">
      {typeLabel(value)}
    </span>
  )
}

const STATUS_STYLE: Record<RuleStatus, string> = {
  PASS: 'text-accent',
  FAIL: 'text-against',
  NA: 'text-ink/40',
  INSUFFICIENT_DATA: 'text-[oklch(48%_0.12_70)]',
}

const STATUS_LABEL: Record<RuleStatus, string> = {
  PASS: 'Pass',
  FAIL: 'Fail',
  NA: 'N/A',
  INSUFFICIENT_DATA: 'No data',
}

export function RuleStatusMark({ status }: { status: RuleStatus }) {
  return <span className={`text-xs font-semibold uppercase tracking-wide ${STATUS_STYLE[status]}`}>{STATUS_LABEL[status]}</span>
}

export function KindTag({ kind }: { kind: RuleFinding['kind'] }) {
  return kind === 'LAW' ? (
    <span className="self-start rounded-sm bg-ink px-1.5 py-px text-[10px] font-bold tracking-widest text-paper">LAW</span>
  ) : (
    <span className="self-start rounded-sm border border-ink/30 px-1.5 py-px text-[10px] font-bold tracking-widest text-ink/60">
      POLICY
    </span>
  )
}

export function ConfidenceBar({ value }: { value: number }) {
  const pct = Math.round(value * 100)
  const tone = value >= 0.6 ? 'bg-ink/70' : 'bg-review'
  return (
    <span className="inline-flex items-center gap-2" title={`Confidence ${pct}%`}>
      <span className="h-1.5 w-16 overflow-hidden rounded-full bg-ink/10">
        <span className={`block h-full ${tone}`} style={{ width: `${pct}%` }} />
      </span>
      <span className="w-8 text-right text-xs text-ink/60">{pct}%</span>
    </span>
  )
}
