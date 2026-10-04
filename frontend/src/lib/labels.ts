import type { Recommendation, ResolutionType } from './types'

const REC_LABEL: Record<Recommendation, string> = {
  FOR: 'For',
  AGAINST: 'Against',
  ABSTAIN: 'Abstain',
  NEEDS_REVIEW: 'Needs review',
}

export function recommendationLabel(value: Recommendation): string {
  return REC_LABEL[value]
}

export function typeLabel(value: ResolutionType | null | undefined): string {
  if (!value) return 'Unclassified'
  return value
    .toLowerCase()
    .split('_')
    .map((w) => (['moa', 'esop'].includes(w) ? w.toUpperCase() : w))
    .join(' ')
    .replace(/^./, (c) => c.toUpperCase())
}
