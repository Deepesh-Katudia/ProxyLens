// Response shapes of the /api/v1 endpoints (app/reports/models.py, app/schemas/analysis.py).
import type { Extraction, ResolutionType } from '../label/api'

export type { Extraction, ResolutionType }

export type Recommendation = 'FOR' | 'AGAINST' | 'ABSTAIN' | 'NEEDS_REVIEW'
export const RECOMMENDATIONS: Recommendation[] = ['FOR', 'AGAINST', 'ABSTAIN', 'NEEDS_REVIEW']

export type JobStatus = 'queued' | 'parsing' | 'extracting' | 'analysing' | 'done' | 'failed'

export type Job = {
  id: string
  document_id: string
  status: JobStatus
  done: number
  total: number
  error: string | null
  created_at: string
  updated_at: string
}

export type CompanyFacts = { turnover_inr: number | null; net_profit_inr: number | null }

export type DocumentMeta = {
  id: string
  filename: string
  file_sha256: string
  company: string | null
  meeting_type: 'AGM' | 'EGM' | 'POSTAL_BALLOT' | 'UNKNOWN' | null
  pages: number | null
  item_count: number | null
  company_facts: CompanyFacts
  job_id: string | null
  uploaded_at: string
}

export type RuleStatus = 'PASS' | 'FAIL' | 'NA' | 'INSUFFICIENT_DATA'

export type RuleFinding = {
  rule_id: string
  kind: 'LAW' | 'POLICY'
  status: RuleStatus
  detail: string
  citation: string
  source_url: string | null
  verified: boolean
}

export type Citation = { regulation_id: string; quote: string }

export type ExtractorInfo = {
  provider: string
  model: string
  latency_ms: number
  valid_first_try: boolean
  used_fallback: boolean
}

export type Resolution = {
  id: string
  document_id: string
  seq: number
  item_no: number
  raw_text: string
  explanatory_statement: string | null
  extracted: Extraction | null
  extractor: ExtractorInfo | null
}

export type Analysis = {
  id: string
  resolution_id: string
  recommendation: Recommendation
  confidence: number
  rationale: string
  rule_findings: RuleFinding[]
  citations: Citation[]
  retrieved_ids: string[]
  flags: string[]
  adjustments: string[]
  pipeline_version: string
  created_at: string
}

export type Feedback = {
  id: string
  analysis_id: string
  analyst_recommendation: Recommendation
  reason: string
  created_at: string
}

export type ReportItem = { resolution: Resolution; analysis: Analysis | null; feedback: Feedback[] }

export type DocumentReport = { document: DocumentMeta; job: Job | null; items: ReportItem[] }

export type UploadResponse = { document_id: string; job_id: string; duplicate: boolean }

export type RegulationView = {
  id: string
  source: string
  citation: string
  heading: string
  text: string
  source_url: string
  as_of: string
  notes: string | null
}
