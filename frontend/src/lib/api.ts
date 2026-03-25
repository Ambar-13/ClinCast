const BASE = typeof window !== 'undefined' && window.location.hostname === 'localhost'
  ? 'http://localhost:8000'
  : '/api'

export const THERAPEUTIC_AREAS = [
  { value: 'cns',            label: 'CNS / Schizophrenia',     ref: 'CATIE (NEJM 2005)' },
  { value: 'oncology',       label: 'Oncology',                ref: 'Tufts CSDD 2019' },
  { value: 'cardiovascular', label: 'Cardiovascular',          ref: 'CHARM / MERIT-HF' },
  { value: 'metabolic',      label: 'Metabolic / T2DM',        ref: 'AACT database' },
  { value: 'alzheimers',     label: "Alzheimer's Disease",     ref: 'A4 Study / AD meta-analysis' },
  { value: 'rare',           label: 'Rare Disease',            ref: 'Tufts CSDD 2019' },
]

export interface RoundSnapshot {
  round_index: number
  time_months: number
  n_enrolled: number
  n_dropout: number
  n_completed: number
  mean_adherence: number
  mean_belief: number
  mean_ae_load: number
  visit_compliance_rate: number
  ae_reporting_mean: number
  enrollment_this_round: number
  dropout_this_round: number
  safety_signal: number
  data_quality: number
  site_burden: number
  n_injection_seeded: number
  active_sites?: number
}

export interface SwarmVote {
  persona?: string
  label?: string
  belief_shift: number
  adherence_shift: number
  reasoning?: string
}

export interface SwarmMetadata {
  belief_shift: number
  adherence_shift: number
  n_agents: number
  n_failed: number
  belief_std: number
  adherence_std: number
  belief_p10: number
  belief_p50: number
  belief_p90: number
  adherence_p10: number
  adherence_p50: number
  adherence_p90: number
  votes: SwarmVote[]
  tag: string
  swarm_error?: string
}

export interface SimulateResponse {
  therapeutic_area: string
  n_patients: number
  n_sites: number
  n_rounds: number
  elapsed_ms: number
  assumed_count: number
  round_snapshots: RoundSnapshot[]
  network_stats: Record<string, number>
  final_stocks: Record<string, number>
  warnings: string[]
  swarm_metadata?: SwarmMetadata
}

export interface CompareResponse {
  scenario_a: SimulateResponse
  scenario_b: SimulateResponse
  delta: Record<string, number>
}

export interface SimulateRequest {
  therapeutic_area: string

  // Trial scale
  n_patients?: number
  n_sites?: number
  n_rounds?: number

  // Concrete visit schedule
  visits_per_month?: number       // 0.5–8
  visit_duration_hours?: number   // 0.5–12
  invasive_procedures?: 'none' | 'blood' | 'lp' | 'biopsy' | 'infusion'
  ediary_frequency?: 'none' | 'weekly' | 'daily'

  // Site & operations
  monitoring_active?: boolean
  site_quality_variance?: 'low' | 'medium' | 'high'
  patient_support_program?: boolean

  // Trial design
  randomization_ratio?: '1:1' | '2:1' | '3:1'
  blinded?: boolean
  competitive_pressure?: 'none' | 'low' | 'medium' | 'high'
  enrollment_rate_modifier?: number  // 0.1–3.0

  // Legacy abstract burden sliders (used when concrete params absent)
  protocol_burden?: number
  protocol_visit_burden?: number

  seed?: number
  use_preset?: boolean

  // Swarm
  use_swarm?: boolean
  n_swarm_agents?: number
  openai_api_key?: string
}

export interface ParsedProtocol {
  title: string
  document_type: string
  confidence: 'high' | 'medium' | 'low'
  assumed_fields: string[]
  params: Partial<SimulateRequest>
  field_sources: Record<string, 'explicit' | 'inferred' | 'default'>
  field_reasoning: Record<string, string>
  summary: string
}

export async function simulate(req: SimulateRequest): Promise<SimulateResponse> {
  const ctrl = new AbortController()
  const timer = setTimeout(() => ctrl.abort(), 300_000) // 5 min — swarm can be large
  const res = await fetch(`${BASE}/simulate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ...req, use_preset: req.use_preset ?? true }),
    signal: ctrl.signal,
  }).finally(() => clearTimeout(timer))
  if (!res.ok) {
    const err = await res.text()
    let msg = err
    try { msg = JSON.parse(err).detail ?? err } catch {}
    throw new Error(`Simulation failed: ${msg}`)
  }
  return res.json()
}

export async function compare(
  a: SimulateRequest,
  b: SimulateRequest,
): Promise<CompareResponse> {
  const res = await fetch(`${BASE}/simulate/compare`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ scenario_a: a, scenario_b: b }),
  })
  if (!res.ok) {
    const err = await res.text()
    let msg = err
    try { msg = JSON.parse(err).detail ?? err } catch {}
    throw new Error(`Simulation failed: ${msg}`)
  }
  return res.json()
}

export async function lookupNct(nctId: string): Promise<NctLookupResult> {
  const res = await fetch(`${BASE}/simulate/nct/${nctId.toUpperCase()}`)
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(err.detail ?? 'NCT lookup failed')
  }
  return res.json()
}

export interface NctLookupResult {
  nct_id: string
  title: string
  therapeutic_area: string
  phase: number | null
  n_patients: number
  n_sites: number
  n_rounds: number
  visits_per_month: number | null
  visit_duration_hours: number | null
  invasive_procedures: string | null
  ediary_frequency: string | null
  monitoring_active: boolean
  patient_support_program: boolean
  blinded: boolean
  has_dsmb: boolean
  extraction_confidence: string
  assumed_fields: string[]
  summary: string
}

export async function applyPolicy(policyConfig: Record<string, number>): Promise<PolicyResult> {
  const res = await fetch(`${BASE}/simulate/policy`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(policyConfig),
  })
  if (!res.ok) throw new Error('Policy application failed')
  return res.json()
}

export interface PolicyResult {
  params: Record<string, number | boolean>
  policy: Record<string, number>
}

export async function parseProtocol(
  file: File,
  openaiApiKey?: string,
): Promise<ParsedProtocol> {
  const form = new FormData()
  form.append('file', file)
  form.append('use_llm', 'true')
  if (openaiApiKey?.trim()) form.append('openai_api_key', openaiApiKey.trim())

  const res = await fetch(`${BASE}/upload/protocol`, {
    method: 'POST',
    body: form,
  })
  if (!res.ok) {
    const err = await res.text()
    let msg = err
    try { msg = JSON.parse(err).detail ?? err } catch {}
    throw new Error(`Simulation failed: ${msg}`)
  }
  return res.json()
}
