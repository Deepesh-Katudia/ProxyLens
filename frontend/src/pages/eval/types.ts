// Shape of an `eval_runs` summary written by `python -m eval.report --db`.

export type EvalMetrics = {
  json_valid: number
  fallback_rate: number | null
  type_accuracy: number
  type_macro_f1: number
  persons_f1: number
  amounts_f1: number
  special_f1: number
  counterparty_f1: number
  latency_p50_ms: number | null
  latency_p95_ms: number | null
  cost_per_1k_usd: number | null
  cost_basis: string
}

export type EvalProvider = {
  name: string
  provider: string
  model: string
  n: number
  run_id: string
  hardware: string
  metrics: EvalMetrics
  confusion: Record<string, Record<string, number>>
}

export type EvalReference = {
  kind: 'human' | 'model' | 'mixed'
  description: string
  items: number
}

export type EvalSummary = {
  run_id: string
  created_at: string
  reference: EvalReference
  providers: EvalProvider[]
  citation_precision: { analyses: number; kept: number; dropped: number; precision: number | null } | null
}
