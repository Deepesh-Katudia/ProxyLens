import type {
  DocumentMeta,
  DocumentReport,
  Feedback,
  Job,
  Recommendation,
  RegulationView,
  UploadResponse,
} from './types'

const BASE = '/api/v1'

export class ApiError extends Error {
  readonly status: number

  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, init)
  if (!res.ok) {
    let detail = res.statusText
    try {
      const body = (await res.json()) as { detail?: unknown }
      if (typeof body.detail === 'string') detail = body.detail
      else if (Array.isArray(body.detail)) detail = 'Invalid input'
    } catch {
      // not JSON; keep the status text
    }
    throw new ApiError(res.status, detail)
  }
  return (await res.json()) as T
}

export const uploadNotice = (file: File, apiKey: string, turnoverCr?: number, netProfitCr?: number) => {
  const form = new FormData()
  form.append('file', file)
  if (turnoverCr !== undefined) form.append('turnover_cr', String(turnoverCr))
  if (netProfitCr !== undefined) form.append('net_profit_cr', String(netProfitCr))
  return request<UploadResponse>('/documents', { method: 'POST', body: form, headers: { 'X-API-Key': apiKey } })
}

export const fetchJob = (jobId: string) => request<Job>(`/jobs/${jobId}`)
export const fetchReport = (documentId: string) => request<DocumentReport>(`/documents/${documentId}`)
export const fetchDocuments = (limit = 12) => request<DocumentMeta[]>(`/documents?limit=${limit}`)
export const fetchRegulation = (id: string) => request<RegulationView>(`/regulations/${encodeURIComponent(id)}`)
export const fetchLatestEval = () => request<Record<string, unknown>>('/eval/latest')

export const submitFeedback = (analysisId: string, recommendation: Recommendation, reason: string, apiKey: string) =>
  request<Feedback>(`/analyses/${analysisId}/feedback`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-API-Key': apiKey },
    body: JSON.stringify({ analyst_recommendation: recommendation, reason }),
  })
