import type { Job, JobStatus } from '../../lib/types'

const STAGES: { status: JobStatus; label: string }[] = [
  { status: 'queued', label: 'Queued' },
  { status: 'parsing', label: 'Reading the PDF' },
  { status: 'extracting', label: 'Extracting resolutions' },
  { status: 'analysing', label: 'Checking rules & reasoning' },
  { status: 'done', label: 'Report ready' },
]

function overall(job: Job): number {
  // Parsing is quick; extraction and analysis each take roughly half the time.
  if (job.status === 'done') return 1
  const share = job.total ? job.done / job.total : 0
  if (job.status === 'extracting') return 0.08 + 0.46 * share
  if (job.status === 'analysing') return 0.54 + 0.46 * share
  return job.status === 'parsing' ? 0.04 : 0
}

export function JobProgress({ job }: { job: Job }) {
  const current = STAGES.findIndex((s) => s.status === job.status)
  const pct = Math.round(overall(job) * 100)
  return (
    <div className="rounded-lg border border-ink/10 bg-white p-5 shadow-[0_1px_0_oklch(0%_0_0/0.04)]">
      <div className="mb-3 flex items-baseline justify-between">
        <p className="font-display text-lg">{job.status === 'failed' ? 'Analysis failed' : 'Analysing notice'}</p>
        {job.status !== 'failed' && <span className="text-sm text-ink/60">{pct}%</span>}
      </div>
      {job.status === 'failed' ? (
        <p className="text-sm text-against">{job.error ?? 'Unknown error'}</p>
      ) : (
        <>
          <div className="h-1.5 overflow-hidden rounded-full bg-ink/10" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}>
            <div className="h-full bg-accent transition-[width] duration-700 ease-out" style={{ width: `${pct}%` }} />
          </div>
          <ol className="mt-4 grid gap-1.5 text-sm sm:grid-cols-5">
            {STAGES.map((stage, i) => (
              <li key={stage.status} className={i < current ? 'text-ink/50' : i === current ? 'font-medium text-ink' : 'text-ink/30'}>
                <span className="mr-1.5">{i < current ? '✓' : i === current ? '●' : '○'}</span>
                {stage.label}
                {i === current && job.total > 0 && (stage.status === 'extracting' || stage.status === 'analysing') && (
                  <span className="ml-1 text-ink/50">
                    {job.done}/{job.total}
                  </span>
                )}
              </li>
            ))}
          </ol>
        </>
      )}
    </div>
  )
}
