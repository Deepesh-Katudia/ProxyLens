import { RESOLUTION_TYPES } from '../../label/api'
import { typeLabel } from '../../lib/labels'

const INVALID = 'INVALID'

export function Confusion({ matrix }: { matrix: Record<string, Record<string, number>> }) {
  const rows = RESOLUTION_TYPES.filter((t) => t in matrix)
  const predicted = new Set(Object.values(matrix).flatMap((r) => Object.keys(r)))
  const cols = [...RESOLUTION_TYPES, INVALID].filter((t) => predicted.has(t) || rows.includes(t as never))
  const peak = Math.max(1, ...Object.values(matrix).flatMap((r) => Object.values(r)))

  return (
    <div className="overflow-x-auto">
      <table className="border-separate border-spacing-0.5 text-[11px]">
        <thead>
          <tr>
            <th className="pr-2 text-right font-normal text-ink/45">reference ↓ predicted →</th>
            {cols.map((c) => (
              <th key={c} className="h-32 w-7 align-bottom font-normal">
                <span className={`inline-block origin-bottom-left translate-x-3 -rotate-60 whitespace-nowrap ${c === INVALID ? 'text-against' : 'text-ink/60'}`}>
                  {c === INVALID ? 'invalid' : typeLabel(c as never).toLowerCase()}
                </span>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r}>
              <th className="pr-2 text-right font-normal whitespace-nowrap text-ink/70">{typeLabel(r)}</th>
              {cols.map((c) => {
                const v = matrix[r]?.[c] ?? 0
                const strength = 0.15 + 0.85 * (v / peak)
                const bg = !v ? 'transparent' : c === r ? `oklch(55% 0.15 155 / ${strength})` : `oklch(48% 0.16 25 / ${strength})`
                return (
                  <td
                    key={c}
                    title={`${typeLabel(r)} → ${c === INVALID ? 'invalid' : typeLabel(c as never)}: ${v}`}
                    className={`h-7 w-7 rounded-sm text-center ${v ? '' : 'bg-ink/[0.03]'} ${v / peak > 0.55 ? 'text-white' : 'text-ink/80'}`}
                    style={{ background: v ? bg : undefined }}
                  >
                    {v || ''}
                  </td>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
