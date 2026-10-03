import { type Extraction, type Money, type Person, RESOLUTION_TYPES, blankPerson } from './api'
import { Field, NumberInput, TextInput, TriState } from './fields'
import { inputClass } from './styles'

type Props = { value: Extraction; onChange: (next: Extraction) => void }

const MAX_KEY_FACTS = 5

export function ExtractionForm({ value, onChange }: Props) {
  const set = <K extends keyof Extraction>(key: K, v: Extraction[K]) => onChange({ ...value, [key]: v })
  const setPerson = (i: number, patch: Partial<Person>) =>
    set('persons', value.persons.map((p, j) => (j === i ? { ...p, ...patch } : p)))
  const setAmount = (i: number, patch: Partial<Money>) =>
    set('amounts', value.amounts.map((a, j) => (j === i ? { ...a, ...patch } : a)))

  return (
    <div className="flex flex-col gap-5">
      <section className="grid grid-cols-[5rem_1fr] gap-3">
        <Field label="Item no.">
          <NumberInput value={value.item_no} onChange={(v) => set('item_no', v ?? 0)} />
        </Field>
        <Field label="Title (≤ 15 words)">
          <TextInput value={value.title} onChange={(v) => set('title', v ?? '')} />
        </Field>
      </section>

      <section className="grid grid-cols-[1fr_auto] items-end gap-3">
        <Field label="Resolution type">
          <select
            className={inputClass}
            value={value.resolution_type}
            onChange={(e) => set('resolution_type', e.target.value as Extraction['resolution_type'])}
          >
            {RESOLUTION_TYPES.map((t) => (
              <option key={t} value={t}>
                {t.replaceAll('_', ' ').toLowerCase()}
              </option>
            ))}
          </select>
        </Field>
        <label className="flex items-center gap-2 pb-2 text-sm">
          <input
            type="checkbox"
            className="size-4 accent-accent"
            checked={value.is_special_resolution}
            onChange={(e) => set('is_special_resolution', e.target.checked)}
          />
          Special resolution
        </label>
      </section>

      <fieldset className="flex flex-col gap-3">
        <legend className="mb-1 text-sm font-semibold">People</legend>
        {value.persons.map((p, i) => (
          <div key={i} className="grid grid-cols-2 gap-2 rounded-lg border border-ink/10 bg-paper p-3">
            <Field label="Name">
              <TextInput value={p.name} onChange={(v) => setPerson(i, { name: v ?? '' })} />
            </Field>
            <Field label="Role">
              <TextInput value={p.role} onChange={(v) => setPerson(i, { role: v })} />
            </Field>
            <Field label="DIN">
              <TextInput value={p.din} onChange={(v) => setPerson(i, { din: v })} />
            </Field>
            <Field label="Age">
              <NumberInput value={p.age} onChange={(v) => setPerson(i, { age: v })} />
            </Field>
            <Field label="Promoter?">
              <TriState value={p.is_promoter} onChange={(v) => setPerson(i, { is_promoter: v })} />
            </Field>
            <Field label="Proposed tenure (yrs)">
              <NumberInput value={p.tenure_years_proposed} onChange={(v) => setPerson(i, { tenure_years_proposed: v })} />
            </Field>
            <Field label="Prior tenure, same role (yrs)">
              <NumberInput value={p.prior_tenure_years} onChange={(v) => setPerson(i, { prior_tenure_years: v })} />
            </Field>
            <Field label="Board attendance %">
              <NumberInput value={p.board_attendance_pct} onChange={(v) => setPerson(i, { board_attendance_pct: v })} />
            </Field>
            <button
              type="button"
              className="col-span-2 justify-self-end text-xs text-red-700 hover:underline"
              onClick={() => set('persons', value.persons.filter((_, j) => j !== i))}
            >
              Remove person
            </button>
          </div>
        ))}
        <button type="button" className="self-start text-sm text-accent hover:underline" onClick={() => set('persons', [...value.persons, blankPerson()])}>
          + Add person
        </button>
      </fieldset>

      <fieldset className="flex flex-col gap-2">
        <legend className="mb-1 text-sm font-semibold">Amounts</legend>
        {value.amounts.map((a, i) => (
          <div key={i} className="grid grid-cols-[1fr_10rem_auto] items-end gap-2">
            <Field label="As written">
              <TextInput value={a.raw} onChange={(v) => setAmount(i, { raw: v ?? '' })} />
            </Field>
            <Field label="Rupees (1 cr = 10,000,000)">
              <NumberInput value={a.amount_inr} onChange={(v) => setAmount(i, { amount_inr: v })} />
            </Field>
            <button type="button" className="pb-2 text-xs text-red-700" onClick={() => set('amounts', value.amounts.filter((_, j) => j !== i))}>
              ✕
            </button>
          </div>
        ))}
        <button
          type="button"
          className="self-start text-sm text-accent hover:underline"
          onClick={() => set('amounts', [...value.amounts, { raw: '', amount_inr: null }])}
        >
          + Add amount
        </button>
      </fieldset>

      <section className="grid grid-cols-2 gap-3">
        <Field label="Counterparty (RPT)">
          <TextInput value={value.counterparty} onChange={(v) => set('counterparty', v)} />
        </Field>
        <Field label="Counterparty is related?">
          <TriState value={value.counterparty_is_related} onChange={(v) => set('counterparty_is_related', v)} />
        </Field>
        <Field label="Transaction nature">
          <TextInput value={value.transaction_nature} onChange={(v) => set('transaction_nature', v)} />
        </Field>
        <Field label="Duration covered (yrs)">
          <NumberInput value={value.duration_years} onChange={(v) => set('duration_years', v)} />
        </Field>
      </section>

      <Field label={`Key facts (one per line, max ${MAX_KEY_FACTS})`}>
        <textarea
          className={`${inputClass} min-h-24`}
          value={value.key_facts.join('\n')}
          onChange={(e) =>
            set(
              'key_facts',
              e.target.value
                .split('\n')
                .slice(0, MAX_KEY_FACTS),
            )
          }
        />
      </Field>
    </div>
  )
}
