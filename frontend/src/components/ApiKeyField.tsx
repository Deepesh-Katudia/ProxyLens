export function ApiKeyField({ value, onChange }: { value: string; onChange: (value: string) => void }) {
  return (
    <label className="flex items-center gap-2 text-xs text-ink/60">
      <span className="shrink-0 font-medium uppercase tracking-wider">API key</span>
      <input
        type="password"
        autoComplete="off"
        className="w-44 rounded border border-ink/15 bg-white px-2 py-1 font-mono text-xs text-ink focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/20"
        placeholder="from .env API_KEY"
        value={value}
        onChange={(e) => onChange(e.target.value)}
      />
    </label>
  )
}
