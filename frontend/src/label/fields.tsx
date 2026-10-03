import type { ReactNode } from 'react'

import { inputClass } from './styles'

export function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="flex flex-col gap-1 text-xs font-medium text-ink/70">
      {label}
      {children}
    </label>
  )
}

export function TextInput({ value, onChange }: { value: string | null; onChange: (v: string | null) => void }) {
  return <input className={inputClass} value={value ?? ''} onChange={(e) => onChange(e.target.value === '' ? null : e.target.value)} />
}

export function NumberInput({ value, onChange }: { value: number | null; onChange: (v: number | null) => void }) {
  return (
    <input
      className={inputClass}
      inputMode="decimal"
      value={value ?? ''}
      onChange={(e) => {
        const raw = e.target.value.trim()
        const parsed = Number(raw)
        onChange(raw === '' || Number.isNaN(parsed) ? null : parsed)
      }}
    />
  )
}

/** Yes / No / Unknown, since most boolean fields can be absent from the notice. */
export function TriState({ value, onChange }: { value: boolean | null; onChange: (v: boolean | null) => void }) {
  const encoded = value === null ? '' : String(value)
  return (
    <select
      className={inputClass}
      value={encoded}
      onChange={(e) => onChange(e.target.value === '' ? null : e.target.value === 'true')}
    >
      <option value="">Not stated</option>
      <option value="true">Yes</option>
      <option value="false">No</option>
    </select>
  )
}

