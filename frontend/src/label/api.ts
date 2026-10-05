export const RESOLUTION_TYPES = [
  'ADOPT_FINANCIALS',
  'DIVIDEND',
  'DIRECTOR_REAPPOINT_ROTATION',
  'INDEPENDENT_DIRECTOR_APPOINT',
  'NON_INDEPENDENT_DIRECTOR_APPOINT',
  'MANAGERIAL_REMUNERATION',
  'RELATED_PARTY_TRANSACTION',
  'AUDITOR_APPOINT',
  'AUDITOR_REMUNERATION_COST',
  'ESOP',
  'CAPITAL_RAISE',
  'BORROWING_LIMITS',
  'ARTICLES_OR_MOA_AMENDMENT',
  'OTHER',
] as const

export type ResolutionType = (typeof RESOLUTION_TYPES)[number]

export type Person = {
  name: string
  role: string | null
  age: number | null
  din: string | null
  is_promoter: boolean | null
  tenure_years_proposed: number | null
  prior_tenure_years: number | null
  board_attendance_pct: number | null
}

export type Money = { amount_inr: number | null; raw: string }

export type Extraction = {
  item_no: number
  title: string
  resolution_type: ResolutionType
  is_special_resolution: boolean
  persons: Person[]
  amounts: Money[]
  counterparty: string | null
  counterparty_is_related: boolean | null
  transaction_nature: string | null
  duration_years: number | null
  key_facts: string[]
}

export type LabelStatus = 'labelled' | 'skipped'

export type GoldLabel = {
  status: LabelStatus
  extraction: Extraction | null
  skip_reason: string | null
  labeller: string
  draft_model?: string | null // model draft the labeller started from and reviewed
}

export type GoldItemSummary = {
  item_id: string
  company: string
  item_no: number
  preview: string
  status: LabelStatus | null
}

export type GoldProgress = {
  total: number
  labelled: number
  skipped: number
  items: GoldItemSummary[]
}

export type GoldItem = {
  item_id: string
  company: string
  file: string
  item_no: number
  section: string | null
  resolution_kind_hint: string | null
  text: string
  explanatory_statement: string | null
  label: GoldLabel | null
  draft: Extraction | null
  draft_model: string | null
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init)
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}))
    const message = typeof detail.detail === 'string' ? detail.detail : JSON.stringify(detail.detail ?? res.statusText)
    throw new Error(`${res.status}: ${message}`)
  }
  return (res.status === 204 ? undefined : await res.json()) as T
}

export const fetchProgress = () => request<GoldProgress>('/api/v1/gold/items')

export const fetchItem = (itemId: string) => request<GoldItem>(`/api/v1/gold/items/${encodeURIComponent(itemId)}`)

export const saveLabel = (itemId: string, label: GoldLabel, apiKey: string) =>
  request<void>(`/api/v1/gold/items/${encodeURIComponent(itemId)}/label`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json', 'X-API-Key': apiKey },
    body: JSON.stringify(label),
  })

export function blankExtraction(item: GoldItem): Extraction {
  return {
    item_no: item.item_no,
    title: '',
    resolution_type: 'OTHER',
    is_special_resolution: item.resolution_kind_hint === 'SPECIAL',
    persons: [],
    amounts: [],
    counterparty: null,
    counterparty_is_related: null,
    transaction_nature: null,
    duration_years: null,
    key_facts: [],
  }
}

export const blankPerson = (): Person => ({
  name: '',
  role: null,
  age: null,
  din: null,
  is_promoter: null,
  tenure_years_proposed: null,
  prior_tenure_years: null,
  board_attendance_pct: null,
})
