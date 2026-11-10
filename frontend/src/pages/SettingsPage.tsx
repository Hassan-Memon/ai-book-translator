import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import {
  getLlmSettings,
  getLocalRuntimes,
  getOcrStatus,
  listModels,
  resetLlmSettings,
  saveLlmSettings,
  testLlmSettings,
} from '../api/client'
import type { LlmSettings, LlmSettingsBody, LlmTestResult, ProviderSpec, Strategy } from '../api/types'
import { useToast } from '../components/Toast'
import { Button, Callout, Card, Field, Icon, Pill, Segmented, Spinner } from '../components/ui'
import { useTitle } from '../lib/useTitle'

type Tab = 'model' | 'ocr' | 'about'

export function SettingsPage() {
  useTitle('Settings', 'Connect your own model: paste an API key or use Ollama / LM Studio on your laptop. Check OCR engines and language packs.')
  const [tab, setTab] = useState<Tab>('model')
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Settings</h1>
          <p className="mt-1 text-sm text-fg-muted">Bring your own key, or your own model. Nothing leaves this machine except the calls you configure.</p>
        </div>
        <Segmented
          value={tab}
          onChange={setTab}
          options={[
            { value: 'model', label: 'Model' },
            { value: 'ocr', label: 'OCR' },
            { value: 'about', label: 'About' },
          ]}
        />
      </div>
      {tab === 'model' && <ModelTab />}
      {tab === 'ocr' && <OcrTab />}
      {tab === 'about' && <AboutTab />}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Model tab
// ---------------------------------------------------------------------------

function ModelTab() {
  const current = useQuery({ queryKey: ['llm-settings'], queryFn: getLlmSettings })
  if (current.isLoading || !current.data) return <Spinner />
  // Remount the form whenever the saved configuration changes so its local
  // state starts from the server values without a seeding effect.
  return <ModelForm key={`${current.data.provider}:${current.data.model}:${current.data.source}`} initial={current.data} />
}

function ModelForm({ initial: c }: { initial: LlmSettings }) {
  const qc = useQueryClient()
  const toast = useToast()
  const runtimes = useQuery({ queryKey: ['local-runtimes'], queryFn: getLocalRuntimes, refetchInterval: 15_000 })

  const [provider, setProvider] = useState(c.provider)
  const [model, setModel] = useState(c.model)
  const [apiKey, setApiKey] = useState<string | null>(null) // null = unchanged
  const [showKey, setShowKey] = useState(false)
  const [baseUrl, setBaseUrl] = useState(c.base_url ?? '')
  const [visionModel, setVisionModel] = useState(c.vision_model ?? '')
  const [test, setTest] = useState<LlmTestResult | null>(null)

  const providers = c.catalog?.providers ?? []
  const spec: ProviderSpec | undefined = providers.find((p) => p.id === provider)
  const local = providers.filter((p) => p.local && p.kind !== 'fake')
  const cloud = providers.filter((p) => !p.local)

  const models = useQuery({
    queryKey: ['models', provider, baseUrl],
    queryFn: () => listModels(provider, baseUrl || undefined),
    enabled: !!provider && provider !== 'fake',
    staleTime: 10_000,
  })

  function choose(p: ProviderSpec) {
    setProvider(p.id)
    setTest(null)
    setApiKey(null)
    setBaseUrl(p.id === c.provider ? (c.base_url ?? p.base_url ?? '') : (p.base_url ?? ''))
    setModel(p.id === c.provider ? c.model : p.default_model)
  }

  const body = useMemo<LlmSettingsBody>(
    () => ({
      provider,
      model: model || null,
      api_key: apiKey,
      base_url: spec?.custom_base_url || spec?.local ? baseUrl || null : null,
      vision_model: visionModel || null,
    }),
    [provider, model, apiKey, baseUrl, visionModel, spec],
  )

  const testing = useMutation({
    mutationFn: () => testLlmSettings(body),
    onSuccess: (r) => setTest(r),
    onError: (e) => toast.error(e),
  })
  const saving = useMutation({
    mutationFn: () => saveLlmSettings(body),
    onSuccess: (r) => {
      toast.success(r.configured ? `Saved: ${r.provider_label} · ${r.model}` : 'Saved, but the provider is not fully configured yet')
      setApiKey(null)
      qc.invalidateQueries({ queryKey: ['llm-settings'] })
      qc.invalidateQueries({ queryKey: ['settings'] })
      qc.invalidateQueries({ queryKey: ['strategy'] })
    },
    onError: (e) => toast.error(e),
  })
  const resetting = useMutation({
    mutationFn: resetLlmSettings,
    onSuccess: () => {
      toast.success('Back to the .env defaults')
      qc.invalidateQueries({ queryKey: ['llm-settings'] })
      qc.invalidateQueries({ queryKey: ['settings'] })
      qc.invalidateQueries({ queryKey: ['strategy'] })
    },
    onError: (e) => toast.error(e),
  })

  const detected = runtimes.data?.runtimes ?? []
  const keyNeeded = !!spec?.needs_key
  const keyMissing = keyNeeded && apiKey === null && !(c.has_api_key && c.provider === provider)

  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-[1.4fr_1fr]">
      <div className="space-y-4">
        {detected.length > 0 && (
          <Callout tone="success" title="Local model server detected">
            {detected.map((r) => (
              <div key={r.provider} className="flex flex-wrap items-center gap-2">
                <span>
                  <strong className="capitalize">{r.provider}</strong> is running with {r.models.length} model{r.models.length === 1 ? '' : 's'}
                  {r.models.length > 0 && <span className="text-fg-muted"> ({r.models.slice(0, 4).join(', ')}{r.models.length > 4 ? '…' : ''})</span>}.
                </span>
                {provider !== r.provider && (
                  <Button size="sm" variant="soft" onClick={() => providers.find((p) => p.id === r.provider) && choose(providers.find((p) => p.id === r.provider)!)}>
                    Use it
                  </Button>
                )}
              </div>
            ))}
          </Callout>
        )}

        <Card title="1. Choose where your model runs" subtitle="Local is free and private. Cloud needs your own API key, stored encrypted on this machine.">
          <div className="mb-2 text-xs font-medium uppercase tracking-wide text-fg-faint">On this machine</div>
          <div className="mb-4 grid grid-cols-1 gap-2 sm:grid-cols-3">
            {local.map((p) => (
              <ProviderCard key={p.id} spec={p} active={provider === p.id} onClick={() => choose(p)} running={detected.some((r) => r.provider === p.id)} />
            ))}
          </div>
          <div className="mb-2 text-xs font-medium uppercase tracking-wide text-fg-faint">Cloud (bring your own key)</div>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            {cloud.map((p) => (
              <ProviderCard key={p.id} spec={p} active={provider === p.id} onClick={() => choose(p)} compact />
            ))}
          </div>
        </Card>

        {spec && (
          <Card title={`2. Configure ${spec.label}`} subtitle={spec.note || undefined}>
            <div className="space-y-3">
              {(spec.local || spec.custom_base_url) && (
                <Field label="Server URL" hint={spec.id === 'ollama' ? 'Default Ollama port is 11434.' : 'The OpenAI-compatible base URL, usually ending in /v1.'}>
                  <input className="input font-mono text-xs" value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} placeholder={spec.base_url ?? 'http://localhost:8080/v1'} />
                </Field>
              )}

              <Field
                label="Model"
                hint={
                  models.data?.source === 'live'
                    ? `${models.data.models.length} model(s) available on the server`
                    : models.data?.error ?? 'Type any model id the provider accepts, or pick a suggestion.'
                }
              >
                <input className="input" list="model-suggestions" value={model} onChange={(e) => setModel(e.target.value)} placeholder={spec.default_model || 'model id'} />
                <datalist id="model-suggestions">
                  {(models.data?.models ?? []).map((m) => (
                    <option key={m.id} value={m.id}>
                      {m.tier ? `${m.tier}${m.vision ? ' · vision' : ''}${m.size_gb ? ` · ${m.size_gb} GB` : ''}` : ''}
                    </option>
                  ))}
                </datalist>
              </Field>
              {models.data?.source === 'live' && models.data.models.length > 0 && (
                <div className="flex flex-wrap gap-1.5">
                  {models.data.models.slice(0, 12).map((m) => (
                    <button
                      key={m.id}
                      type="button"
                      onClick={() => setModel(m.id)}
                      className={`rounded-full border px-2.5 py-0.5 text-xs transition ${
                        model === m.id ? 'border-brand bg-brand-soft text-brand' : 'border-border text-fg-muted hover:border-border-strong hover:text-fg'
                      }`}
                      title={`${m.tier ?? ''} ${m.vision ? '· vision' : ''}`}
                    >
                      {m.id}
                      {m.vision && <Icon name="eye" size={11} className="ms-1" />}
                    </button>
                  ))}
                </div>
              )}
              {models.data?.running === false && (
                <Callout tone="warn">
                  {models.data.error}. Start the server, then press <em>Refresh</em>.{' '}
                  <button className="underline" onClick={() => models.refetch()}>
                    Refresh
                  </button>
                </Callout>
              )}

              {spec.needs_key && (
                <Field
                  label="API key"
                  hint={
                    <>
                      {c.provider === provider && c.has_api_key && apiKey === null ? `A key is saved (${c.api_key_hint}). Leave empty to keep it.` : 'Stored encrypted in the local database; never shown again.'}{' '}
                      {spec.key_url && (
                        <a href={spec.key_url} target="_blank" rel="noreferrer" className="text-brand hover:underline">
                          Get a key <Icon name="external" size={10} />
                        </a>
                      )}
                    </>
                  }
                >
                  <div className="flex gap-2">
                    <input
                      className="input font-mono text-xs"
                      type={showKey ? 'text' : 'password'}
                      autoComplete="off"
                      value={apiKey ?? ''}
                      onChange={(e) => setApiKey(e.target.value)}
                      placeholder={c.provider === provider && c.has_api_key ? '•••••••• (saved)' : 'paste your key'}
                    />
                    <Button type="button" onClick={() => setShowKey((v) => !v)} aria-label="Toggle key visibility">
                      <Icon name={showKey ? 'eyeOff' : 'eye'} />
                    </Button>
                  </div>
                </Field>
              )}

              <Field label="Vision model for OCR of scanned pages (optional)" hint="Only poor OCR pages are sent to it. Leave empty to use the chat model when it has vision, or none.">
                <input className="input" value={visionModel} onChange={(e) => setVisionModel(e.target.value)} placeholder={spec.id === 'ollama' ? 'qwen2.5vl:7b' : spec.id === 'openai' ? 'gpt-4.1-mini' : 'same as chat model'} />
              </Field>

              <div className="flex flex-wrap items-center gap-2 border-t border-border pt-3">
                <Button onClick={() => testing.mutate()} loading={testing.isPending} disabled={!model}>
                  <Icon name="zap" /> Test connection
                </Button>
                <Button variant="primary" onClick={() => saving.mutate()} loading={saving.isPending} disabled={!model || keyMissing}>
                  <Icon name="check" /> Save
                </Button>
                {c.source === 'ui' && (
                  <Button variant="ghost" onClick={() => resetting.mutate()} loading={resetting.isPending}>
                    Reset to .env
                  </Button>
                )}
                {keyMissing && <span className="text-xs text-warn">An API key is required for this provider.</span>}
              </div>
              {test && <TestResult result={test} />}
            </div>
          </Card>
        )}
      </div>

      <div className="space-y-4">
        <Card title="Current configuration">
          <div className="space-y-2 text-sm">
            <Row label="Provider" value={c.provider_label} />
            <Row label="Model" value={c.model || '—'} />
            <Row label="Runs" value={c.is_local ? 'on this machine (free)' : 'in the cloud'} />
            <Row label="Model size" value={c.model_tier} />
            <Row label="Vision OCR" value={c.supports_vision ? 'available' : 'not available'} />
            <Row label="Key" value={c.needs_key ? (c.has_api_key ? `saved · ${c.api_key_hint}` : 'missing') : 'not needed'} />
            <Row label="Source" value={c.source === 'ui' ? 'Settings screen' : '.env defaults'} />
            {!c.configured && c.error && <Callout tone="warn">{c.error}</Callout>}
          </div>
        </Card>
        {c.strategy && <StrategyCard strategy={c.strategy} model={c.model} />}
        <LocalRecommendations recs={c.catalog?.local_recommendations ?? []} onPick={(name) => {
          const p = providers.find((x) => x.id === 'ollama')
          if (p) {
            choose(p)
            setModel(name)
          }
        }} />
      </div>
    </div>
  )
}

function ProviderCard({ spec, active, onClick, running, compact }: { spec: ProviderSpec; active: boolean; onClick: () => void; running?: boolean; compact?: boolean }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`relative rounded-xl border text-left transition ${compact ? 'p-2.5' : 'p-3'} ${
        active ? 'border-brand bg-brand-soft shadow-sm' : 'border-border bg-surface hover:border-border-strong hover:bg-surface-2'
      }`}
    >
      <div className="flex items-center gap-2">
        <span className={`grid h-7 w-7 place-items-center rounded-lg ${active ? 'bg-brand text-brand-fg' : 'bg-surface-2 text-fg-muted'}`}>
          <Icon name={spec.local ? 'cpu' : 'cloud'} size={14} />
        </span>
        <span className="min-w-0">
          <span className="block truncate text-sm font-medium text-fg">{spec.label}</span>
          {!compact && <span className="block text-[11px] text-fg-muted">{spec.needs_key ? 'needs key' : 'no key needed'}</span>}
        </span>
      </div>
      {running && (
        <span className="absolute right-2 top-2">
          <Pill tone="success">running</Pill>
        </span>
      )}
      {!compact && spec.note && <div className="mt-2 line-clamp-2 text-[11px] leading-4 text-fg-muted">{spec.note}</div>}
    </button>
  )
}

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-3 border-b border-border py-1.5 last:border-0">
      <span className="text-xs text-fg-muted">{label}</span>
      <span className="text-right text-sm text-fg">{value}</span>
    </div>
  )
}

function TestResult({ result }: { result: LlmTestResult }) {
  if (result.ok) {
    return (
      <Callout tone="success" title={`Connected · ${result.latency_ms} ms`}>
        The model replied “{result.reply}”. Size: {result.model_tier}. {result.supports_vision ? 'It can read images, so poor OCR pages can escalate to it.' : 'It cannot read images; OCR stays on the free engines.'}
        {result.is_local && ' Runs locally: $0 per call.'}
      </Callout>
    )
  }
  return (
    <Callout tone="danger" title={result.stage === 'config' ? 'Configuration problem' : 'The call failed'}>
      {result.error}
    </Callout>
  )
}

function StrategyCard({ strategy: s, model }: { strategy: Strategy; model: string }) {
  const items: Array<[boolean, string, string]> = [
    [s.sentence_alignment, 'Sentence alignment', 'numbered sentences in, numbered sentences out: a dropped sentence is caught deterministically'],
    [s.gate, 'Quality gate', 'script, length ratio, structure, glossary and alignment checks before any LLM review'],
    [s.verify, 'LLM review', 'a reviewer scores the chunk and proposes span-level fixes'],
    [s.max_retries > 0, `Retry ≤ ${s.max_retries}`, 'the translator gets the exact findings back'],
    [s.polish, 'Polish pass', 'fluency edit accepted only if the gate does not get worse'],
    [s.candidates > 1, `${s.candidates} candidates`, 'sample several translations, keep the one the gate prefers'],
    [s.memory_examples > 0, `${s.memory_examples} memory examples`, 'approved chunks of the same book as in-context examples'],
    [s.ocr_cleanup !== 'off', `OCR repair (${s.ocr_cleanup})`, 'the text model fixes OCR noise before translating poor chunks'],
  ]
  return (
    <Card title="What this model will get" subtitle={`${model || 'current model'} · ${s.tier} · ${s.profile} profile`}>
      <ul className="space-y-1.5 text-xs">
        {items.map(([on, name, why]) => (
          <li key={name} className={`flex gap-2 ${on ? '' : 'opacity-50'}`}>
            <Icon name={on ? 'check' : 'x'} size={14} className={`mt-0.5 ${on ? 'text-success' : 'text-fg-faint'}`} />
            <span>
              <span className="font-medium text-fg">{name}</span> <span className="text-fg-muted">· {why}</span>
            </span>
          </li>
        ))}
      </ul>
      <div className="mt-2 text-[11px] text-fg-faint">chunks ≈ {s.chunk_target_chars} chars · tagged output: {s.tagged_output ? 'yes' : 'no (native JSON)'}</div>
    </Card>
  )
}

function LocalRecommendations({ recs, onPick }: { recs: Array<{ name: string; params_b: number; ram_gb: number; vision: boolean; languages: string; best_for: string; tags: string[] }>; onPick: (name: string) => void }) {
  if (!recs.length) return null
  return (
    <Card title="Small models that run on a laptop" subtitle="Pull with `ollama pull <name>`. The agent strategy adapts to the size automatically.">
      <ul className="divide-y divide-border text-xs">
        {recs.map((m) => (
          <li key={m.name} className="flex items-start justify-between gap-2 py-2">
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-1.5">
                <code className="rounded bg-surface-2 px-1.5 py-0.5 font-mono text-[11px] text-fg">{m.name}</code>
                <span className="text-fg-faint">{m.params_b}B · ~{m.ram_gb} GB RAM</span>
                {m.vision && (
                  <Pill tone="info">
                    <Icon name="eye" size={10} /> vision
                  </Pill>
                )}
                {m.tags.includes('recommended') && <Pill tone="brand">recommended</Pill>}
              </div>
              <div className="mt-0.5 text-fg-muted">{m.best_for}</div>
            </div>
            <Button size="sm" variant="ghost" onClick={() => onPick(m.name)} title="Use with Ollama">
              Use
            </Button>
          </li>
        ))}
      </ul>
    </Card>
  )
}

// ---------------------------------------------------------------------------
// OCR tab
// ---------------------------------------------------------------------------

function OcrTab() {
  const status = useQuery({ queryKey: ['ocr-status'], queryFn: getOcrStatus })
  if (status.isLoading || !status.data) return <Spinner />
  const s = status.data
  const anyFree = s.engines.some((e) => e.available && e.name !== 'easyocr')
  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-[1.4fr_1fr]">
      <div className="space-y-4">
        <Card title="OCR engines" subtitle="Scanned pages are read for free, without a model. The ladder tries these in order and escalates only poor pages.">
          <ul className="divide-y divide-border">
            {s.engines.map((e) => (
              <li key={e.name} className="flex items-start justify-between gap-3 py-2.5">
                <div>
                  <div className="flex items-center gap-2 text-sm font-medium">
                    <span className={`h-2 w-2 rounded-full ${e.available ? 'bg-success' : 'bg-fg-faint'}`} />
                    {e.label}
                    {e.confidence && <Pill>word confidences</Pill>}
                  </div>
                  <div className="mt-0.5 text-xs text-fg-muted">{e.hint}</div>
                </div>
                <Pill tone={e.available ? 'success' : 'neutral'}>{e.available ? 'available' : 'not installed'}</Pill>
              </li>
            ))}
          </ul>
          {!anyFree && (
            <Callout tone="warn" className="mt-3">
              No free engine is available, so scanned books will fail to extract until Tesseract is installed or a vision model is configured.
            </Callout>
          )}
        </Card>
        <Card title="Language packs" subtitle={`Tesseract traineddata files. Missing packs ${s.download_packs ? 'download automatically' : 'are NOT downloaded (OCR_DOWNLOAD_PACKS=false)'} from tessdata_${s.pack_repo}.`}>
          <div className="flex flex-wrap gap-1.5">
            {s.installed_packs.length === 0 && <span className="text-sm text-fg-muted">No packs installed yet; the first scanned book will fetch what it needs.</span>}
            {s.installed_packs.map((p) => (
              <code key={p} className="rounded bg-surface-2 px-1.5 py-0.5 font-mono text-xs">
                {p}
              </code>
            ))}
          </div>
          <div className="mt-3 space-y-1 text-xs text-fg-muted">
            <div>
              Managed directory: <code className="font-mono">{s.tessdata_dir}</code>
            </div>
            {s.system_tessdata_dirs.length > 0 && (
              <div>
                System directories: <code className="font-mono">{s.system_tessdata_dirs.join(', ')}</code>
              </div>
            )}
          </div>
        </Card>
      </div>
      <div className="space-y-4">
        <Card title="How a scanned page is read">
          <ol className="list-decimal space-y-1.5 ps-4 text-xs text-fg-muted">
            <li>Render at {s.dpi} dpi, greyscale, auto-contrast.</li>
            <li>Recognise words with boxes and confidences (packs for the source and target languages, plus English for citations).</li>
            <li>Rebuild lines, detect columns and scanned spreads, read right-to-left or left-to-right, drop page numbers and running heads.</li>
            <li>Score the page: confidence, share of letters in the expected script, garbage ratio.</li>
            <li>
              Below {s.escalation_threshold}: try the next free engine; then, if a vision model is configured (policy: <em>{s.vision_policy}</em>), re-read the page with it.
            </li>
            <li>Chunks keep their score, so review shows which parts to trust, and the translator can repair OCR noise first.</li>
          </ol>
        </Card>
        <Callout tone="info" title="Honest limits">
          Tesseract reads printed Arabic, Latin, Cyrillic and Indic scripts well. It is weak on Urdu Nastaliq, handwriting and very faint prints. For those, a small local vision model such as <code>qwen2.5vl:7b</code> or <code>gemma3:4b</code> gives far better text, and you only pay (in time) for the pages that need it.
        </Callout>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// About tab
// ---------------------------------------------------------------------------

function AboutTab() {
  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
      <Card title="TranslateBook AI">
        <div className="space-y-3 text-sm text-fg-muted">
          <p>
            An open-source workbench for translating whole books. Upload a PDF, choose any two of 50+ languages, and the pipeline
            extracts structure, translates chunk by chunk with an agent that checks its own work, flags terminology for one human
            decision per term, and exports a DOCX in the right font and direction.
          </p>
          <p>
            It runs on your machine. Your books, your glossary and your API keys never leave it unless you point it at a cloud
            model. With Ollama or LM Studio the whole thing is free.
          </p>
          <div className="flex flex-wrap gap-2 pt-1">
            <a href="https://github.com/Hassan-Memon/ai-book-translator" target="_blank" rel="noreferrer">
              <Button size="sm">
                <Icon name="github" /> GitHub
              </Button>
            </a>
            <a href="https://github.com/Hassan-Memon/ai-book-translator/tree/main/docs" target="_blank" rel="noreferrer">
              <Button size="sm">
                <Icon name="book" /> Documentation
              </Button>
            </a>
          </div>
        </div>
      </Card>
      <Card title="Keyboard shortcuts (review screen)">
        <ul className="space-y-1.5 text-sm text-fg-muted">
          <li>
            <kbd>j</kbd> / <kbd>k</kbd> next / previous chunk
          </li>
          <li>
            <kbd>a</kbd> approve the selected chunk
          </li>
          <li>
            <kbd>e</kbd> focus the translation editor
          </li>
        </ul>
      </Card>
    </div>
  )
}
