import { useEffect, useState } from 'react'
import { fetchJob } from '../../lib/api'
import type { Job } from '../../lib/types'

const POLL_MS = 1500

export function useJob(jobId: string | null): { job: Job | null; error: string | null } {
  const [job, setJob] = useState<Job | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!jobId) return
    let stopped = false
    let timer: number | undefined
    const poll = async () => {
      try {
        const next = await fetchJob(jobId)
        if (stopped) return
        setJob(next)
        if (next.status !== 'done' && next.status !== 'failed') timer = window.setTimeout(poll, POLL_MS)
      } catch (e) {
        if (!stopped) setError(e instanceof Error ? e.message : 'Lost contact with the API')
      }
    }
    void poll()
    return () => {
      stopped = true
      window.clearTimeout(timer)
    }
  }, [jobId])

  return { job, error }
}
