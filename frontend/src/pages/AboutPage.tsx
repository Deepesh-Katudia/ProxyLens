const PIPELINE = [
  ['Parse', 'PyMuPDF text, running headers stripped, agenda items and Section 102 statements aligned'],
  ['Extract', 'Fine-tuned Qwen2.5-3B (QLoRA, GGUF Q4_K_M on CPU); one repair, then teacher fallback'],
  ['Validate', 'Notice numbering and “as a Special Resolution” wording override the model'],
  ['Retrieve', 'MongoDB Atlas $vectorSearch over SEBI LODR + Companies Act, filtered by resolution type'],
  ['Rule check', '11 deterministic checks from policy.yaml, tagged LAW or POLICY'],
  ['Reason', 'Teacher LLM recommends a vote with quoted citations'],
  ['Guardrails', 'Unverifiable citations dropped; LAW failures block FOR; uncertainty goes to review'],
] as const

export function AboutPage() {
  return (
    <div className="grid gap-12 lg:grid-cols-[1fr_22rem]">
      <article>
        <p className="text-xs font-semibold uppercase tracking-[0.2em] text-accent">About</p>
        <h1 className="mt-2 font-display text-4xl font-semibold tracking-tight">How ProxyLens decides</h1>
        <p className="mt-4 max-w-2xl leading-relaxed text-ink/75">
          Institutional investors vote on thousands of AGM and EGM resolutions each season. ProxyLens does the first pass
          an analyst would: read the notice, pull out each resolution, check it against SEBI LODR and the Companies Act
          2013, and recommend a vote with the clauses that support it. Anything the facts cannot settle is sent to a human.
        </p>

        <h2 className="mt-12 mb-5 text-xs font-semibold uppercase tracking-[0.18em] text-ink/50">Pipeline (LangGraph)</h2>
        <ol className="relative space-y-0 border-l-2 border-ink/15 pl-0">
          {PIPELINE.map(([name, text], i) => (
            <li key={name} className="relative grid grid-cols-[2.5rem_8rem_1fr] items-baseline gap-3 py-3 pl-4">
              <span className="absolute -left-[7px] top-[1.15rem] h-3 w-3 rounded-full border-2 border-paper bg-ink" aria-hidden />
              <span className="font-display text-ink/35">{String(i + 1).padStart(2, '0')}</span>
              <span className="font-semibold">{name}</span>
              <span className="text-sm text-ink/70">{text}</span>
            </li>
          ))}
        </ol>

        <h2 className="mt-12 mb-3 text-xs font-semibold uppercase tracking-[0.18em] text-ink/50">The model</h2>
        <p className="max-w-2xl leading-relaxed text-ink/75">
          The extractor is Qwen2.5-3B-Instruct, fine-tuned with QLoRA on 1,504 resolutions labelled by a frontier teacher
          model, then quantised to a 1.9 GB GGUF that runs on CPU. Analyst overrides are stored as feedback for the next
          training round.
        </p>
      </article>

      <aside className="space-y-6 lg:pt-16">
        <div className="rounded-lg border border-against/30 bg-white p-5">
          <p className="font-semibold">Disclaimer</p>
          <p className="mt-2 text-sm leading-relaxed text-ink/70">
            Research and educational tool. Not investment or voting advice. Regulations change; rule parameters carry a
            source URL and an as-of date, and some Companies Act checks are not yet re-verified against the amended Act.
          </p>
        </div>
        <div className="rounded-lg border border-ink/10 bg-white p-5 text-sm">
          <p className="font-semibold">Links</p>
          <ul className="mt-2 space-y-1.5">
            <li>
              <a className="underline decoration-ink/30 hover:decoration-ink" href="https://github.com/Deepesh-Katudia/ProxyLens" target="_blank" rel="noreferrer">
                Source code on GitHub
              </a>
            </li>
            <li className="text-ink/60">Model weights: Hugging Face Hub (private while in development)</li>
          </ul>
        </div>
      </aside>
    </div>
  )
}
