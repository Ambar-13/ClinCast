"use client";

import { useState } from "react";
import { ChevronDown, ChevronUp, Search, X } from "lucide-react";
import { THERAPEUTIC_AREAS, SimulateRequest, lookupNct, NctLookupResult } from "@/lib/api";

interface Props {
  value: SimulateRequest;
  onChange: (v: SimulateRequest) => void;
  label?: string;
}

// ── Tiny helpers ──────────────────────────────────────────────────────────────

function Label({ children }: { children: React.ReactNode }) {
  return (
    <span className="block text-[11px] font-medium mb-1" style={{ color: "var(--ink-600)" }}>
      {children}
    </span>
  );
}

function Hint({ children }: { children: React.ReactNode }) {
  return <p className="mt-0.5 text-[10px] leading-4" style={{ color: "var(--ink-400)" }}>{children}</p>;
}

function Section({
  title, children, defaultOpen = true,
}: { title: string; children: React.ReactNode; defaultOpen?: boolean }) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="border-t pt-4" style={{ borderColor: "var(--border-warm)" }}>
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="flex w-full items-center justify-between mb-3"
      >
        <p className="kicker text-[10px]">{title}</p>
        {open
          ? <ChevronUp size={12} style={{ color: "var(--ink-400)" }} />
          : <ChevronDown size={12} style={{ color: "var(--ink-400)" }} />}
      </button>
      {open && children}
    </div>
  );
}

function SliderField({
  label, hint, value, min, max, step, format, onChange,
}: {
  label: string; hint?: string; value: number;
  min: number; max: number; step: number;
  format: (v: number) => string;
  onChange: (v: number) => void;
}) {
  return (
    <div>
      <div className="flex items-center justify-between mb-1">
        <Label>{label}</Label>
        <span className="text-xs font-semibold font-mono" style={{ color: "var(--primary-700)" }}>
          {format(value)}
        </span>
      </div>
      <input
        type="range" min={min} max={max} step={step} value={value}
        onChange={(e) => onChange(parseFloat(e.target.value))}
        className="w-full accent-[var(--primary-700)] h-1.5 cursor-pointer"
      />
      {hint && <Hint>{hint}</Hint>}
    </div>
  );
}

function NumberField({
  label, hint, value, min, max, placeholder, onChange,
}: {
  label: string; hint?: string; value?: number; min: number; max: number;
  placeholder?: string; onChange: (v: number | undefined) => void;
}) {
  return (
    <div>
      <Label>{label}</Label>
      <input
        type="number" min={min} max={max}
        value={value ?? ""}
        placeholder={placeholder ?? "preset"}
        onChange={(e) => onChange(e.target.value ? parseInt(e.target.value) : undefined)}
        className="input-warm w-full"
      />
      {hint && <Hint>{hint}</Hint>}
    </div>
  );
}

function SelectField<T extends string>({
  label, hint, value, options, onChange,
}: {
  label: string; hint?: string; value: T | undefined;
  options: { value: T; label: string }[];
  onChange: (v: T) => void;
}) {
  return (
    <div>
      <Label>{label}</Label>
      <select
        value={value ?? ""}
        onChange={(e) => onChange(e.target.value as T)}
        className="select-warm w-full"
      >
        {options.map((o) => (
          <option key={o.value} value={o.value}>{o.label}</option>
        ))}
      </select>
      {hint && <Hint>{hint}</Hint>}
    </div>
  );
}

function Toggle({
  label, hint, checked, onChange,
}: { label: string; hint?: string; checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <label className="flex cursor-pointer items-start gap-3">
      <div className="relative mt-0.5 flex-shrink-0">
        <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} className="peer sr-only" />
        <div className="h-4 w-8 rounded-full transition-colors"
          style={{ background: checked ? "var(--primary-700)" : "var(--surface-200)" }} />
        <div className="absolute top-0.5 h-3 w-3 rounded-full bg-white shadow transition-transform"
          style={{ left: "2px", transform: checked ? "translateX(16px)" : "translateX(0)" }} />
      </div>
      <div className="min-w-0 flex-1">
        <span className="text-xs font-medium" style={{ color: "var(--ink-700)" }}>{label}</span>
        {hint && <Hint>{hint}</Hint>}
      </div>
    </label>
  );
}

// ── NCT Lookup ────────────────────────────────────────────────────────────────

function confidenceColor(c: string): { bg: string; text: string; border: string } {
  if (c === "high")   return { bg: "rgba(22,163,74,0.10)",   text: "#16a34a", border: "rgba(22,163,74,0.25)" };
  if (c === "medium") return { bg: "rgba(7,160,195,0.08)",   text: "var(--primary-700)", border: "rgba(7,160,195,0.22)" };
  return               { bg: "rgba(220,38,38,0.10)",   text: "#dc2626", border: "rgba(220,38,38,0.25)" };
}

function NctLookup({ onApply }: { onApply: (fields: Partial<SimulateRequest>) => void }) {
  const [open,    setOpen]    = useState(false);
  const [nctId,   setNctId]   = useState("");
  const [loading, setLoading] = useState(false);
  const [result,  setResult]  = useState<NctLookupResult | null>(null);
  const [error,   setError]   = useState<string | null>(null);
  const [assumed, setAssumed] = useState(false);

  async function lookup() {
    if (!nctId.trim()) return;
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const data = await lookupNct(nctId.trim());
      setResult(data);
      // Auto-apply on success
      const patch: Partial<SimulateRequest> = {
        therapeutic_area:      data.therapeutic_area,
        n_patients:            data.n_patients,
        n_sites:               data.n_sites,
        n_rounds:              data.n_rounds,
        monitoring_active:     data.monitoring_active,
        patient_support_program: data.patient_support_program,
        blinded:               data.blinded,
      };
      if (data.visits_per_month     != null) patch.visits_per_month     = data.visits_per_month;
      if (data.visit_duration_hours != null) patch.visit_duration_hours = data.visit_duration_hours;
      if (data.invasive_procedures  != null) patch.invasive_procedures  = data.invasive_procedures as SimulateRequest["invasive_procedures"];
      if (data.ediary_frequency     != null) patch.ediary_frequency     = data.ediary_frequency    as SimulateRequest["ediary_frequency"];
      onApply(patch);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }

  function clear() {
    setResult(null);
    setError(null);
    setNctId("");
    setAssumed(false);
  }

  const conf = result ? confidenceColor(result.extraction_confidence) : null;

  return (
    <div className="border-b pb-4 mb-4" style={{ borderColor: "var(--border-warm)" }}>
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="flex w-full items-center justify-between text-left"
      >
        <div className="flex items-center gap-2">
          <Search size={12} style={{ color: "var(--primary-600)" }} />
          <span className="text-[11px] font-semibold" style={{ color: "var(--ink-700)" }}>
            Auto-fill from ClinicalTrials.gov
          </span>
        </div>
        {open
          ? <ChevronUp size={12} style={{ color: "var(--ink-400)" }} />
          : <ChevronDown size={12} style={{ color: "var(--ink-400)" }} />}
      </button>

      {open && (
        <div className="mt-3 space-y-2.5">
          <div className="flex gap-2">
            <input
              type="text"
              value={nctId}
              onChange={(e) => setNctId(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") lookup(); }}
              placeholder="NCT12345678"
              className="input-warm flex-1 font-mono text-xs"
              spellCheck={false}
            />
            <button
              type="button"
              onClick={lookup}
              disabled={loading || !nctId.trim()}
              className="btn-primary px-3 py-1.5 text-xs shrink-0"
            >
              {loading ? (
                <svg className="animate-spin h-3 w-3" viewBox="0 0 24 24" fill="none">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                </svg>
              ) : "Lookup"}
            </button>
          </div>

          {error && (
            <p className="text-[11px] rounded px-2 py-1.5"
              style={{ color: "#dc2626", background: "rgba(220,38,38,0.08)", border: "1px solid rgba(220,38,38,0.2)" }}>
              {error}
            </p>
          )}

          {result && conf && (
            <div className="rounded-lg px-3 py-2.5 space-y-2"
              style={{ background: "var(--surface-50)", border: "1px solid var(--border-warm)" }}>
              {/* Title + clear */}
              <div className="flex items-start justify-between gap-2">
                <div className="flex items-start gap-2 min-w-0">
                  <span className="mt-0.5 shrink-0 inline-flex items-center rounded-full px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-widest"
                    style={{ background: "rgba(22,163,74,0.10)", color: "#16a34a", border: "1px solid rgba(22,163,74,0.25)" }}>
                    Applied
                  </span>
                  <p className="text-[11px] font-medium leading-4" style={{ color: "var(--ink-800)" }}>
                    {result.title}
                  </p>
                </div>
                <button type="button" onClick={clear} className="shrink-0 mt-0.5">
                  <X size={12} style={{ color: "var(--ink-400)" }} />
                </button>
              </div>

              {/* NCT ID + confidence */}
              <div className="flex items-center gap-2 flex-wrap">
                <span className="font-mono text-[10px]" style={{ color: "var(--ink-500)" }}>{result.nct_id}</span>
                <span className="inline-flex items-center rounded-full px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-widest"
                  style={{ background: conf.bg, color: conf.text, border: `1px solid ${conf.border}` }}>
                  {result.extraction_confidence} confidence
                </span>
              </div>

              {/* Assumed fields */}
              {result.assumed_fields.length > 0 && (
                <div>
                  <button
                    type="button"
                    onClick={() => setAssumed(!assumed)}
                    className="flex items-center gap-1 text-[10px]"
                    style={{ color: "var(--ink-400)" }}
                  >
                    <span>ⓘ {result.assumed_fields.length} field{result.assumed_fields.length !== 1 ? "s" : ""} inferred</span>
                    {assumed ? <ChevronUp size={10} /> : <ChevronDown size={10} />}
                  </button>
                  {assumed && (
                    <div className="mt-1.5 flex flex-wrap gap-1">
                      {result.assumed_fields.map((f) => (
                        <span key={f} className="rounded px-1.5 py-0.5 font-mono text-[9px]"
                          style={{ background: "rgba(7,160,195,0.07)", color: "var(--primary-700)", border: "1px solid rgba(7,160,195,0.18)" }}>
                          {f}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── Policy narrative ──────────────────────────────────────────────────────────

function policyNarrative(v: SimulateRequest): string {
  const ta: Record<string, string> = {
    cns: "CNS / schizophrenia", oncology: "oncology", cardiovascular: "cardiovascular",
    metabolic: "metabolic / T2DM", alzheimers: "Alzheimer's disease", rare: "rare disease",
  };
  const area = ta[v.therapeutic_area] ?? v.therapeutic_area;
  const pts  = v.n_patients  ?? 400;
  const sites= v.n_sites     ?? 20;
  const mos  = v.n_rounds    ?? 18;

  // Scale
  const scale = pts >= 800 ? "large-scale" : pts >= 300 ? "mid-size" : "small";

  // Burden
  const visitsHigh  = (v.visits_per_month  ?? 2) >= 3;
  const durationHigh= (v.visit_duration_hours ?? 1.5) >= 3;
  const invasive    = v.invasive_procedures && v.invasive_procedures !== "none";
  const eDiary      = v.ediary_frequency && v.ediary_frequency !== "none";
  const burdenLevel = [visitsHigh, durationHigh, invasive, eDiary].filter(Boolean).length;
  const burden      = burdenLevel >= 3 ? "high-burden" : burdenLevel >= 1 ? "moderate-burden" : "low-burden";

  // Support
  const hasRBM     = v.monitoring_active !== false;
  const hasSupport = v.patient_support_program === true;

  // Design
  const ratio      = v.randomization_ratio ?? "1:1";
  const blinded    = v.blinded !== false;
  const pressure   = v.competitive_pressure ?? "none";

  // Sentences
  const sentences: string[] = [];

  sentences.push(
    `This organisation is running a ${scale} ${area} trial across ${sites} sites over ${mos} months with ${pts} patients.`
  );

  if (burden === "high-burden") {
    sentences.push("The protocol is demanding — frequent visits, long appointments, and invasive procedures signal a late-phase efficacy study willing to accept high dropout risk for rigorous data.");
  } else if (burden === "moderate-burden") {
    sentences.push("The protocol is moderately burdensome — a reasonable trade-off between data richness and patient retention.");
  } else {
    sentences.push("The protocol is patient-friendly — minimal visits and no invasive procedures, prioritising retention over data density.");
  }

  if (hasSupport && hasRBM) {
    sentences.push("The org is investing heavily in execution quality: risk-based monitoring catches site problems early, and the patient support programme (coordinators, transport, SMS reminders) directly fights dropout.");
  } else if (hasSupport) {
    sentences.push("A patient support programme is in place — the org is betting on retention over remote monitoring efficiency.");
  } else if (hasRBM) {
    sentences.push("Risk-based monitoring is active — the org is using data-driven site oversight rather than blanket on-site visits, suggesting cost discipline.");
  } else {
    sentences.push("No monitoring enhancements or patient support — the org is running lean, accepting higher data-quality and dropout risk.");
  }

  if (ratio !== "1:1") {
    sentences.push(`A ${ratio} randomisation ratio means more patients land on treatment — this improves recruitment appeal but makes the placebo arm smaller and noisier.`);
  }

  if (!blinded) {
    sentences.push("The trial is open-label — patients know their assignment. This cuts protocol overhead but raises dropout risk in the control arm significantly.");
  }

  if (pressure === "high" || pressure === "medium") {
    sentences.push(`With ${pressure} competitive pressure, rival trials and media scrutiny will erode patient belief mid-run — expect a steeper dropout curve in later months.`);
  }

  if ((v.site_quality_variance ?? "medium") === "high") {
    sentences.push("High site heterogeneity means a handful of sites will drive most of your data while others struggle — the org needs active site management to avoid a skewed dataset.");
  }

  return sentences.join(" ");
}

// ── Main panel ────────────────────────────────────────────────────────────────

export function TrialConfigPanel({ value, onChange, label }: Props) {
  const set = <K extends keyof SimulateRequest>(k: K, v: SimulateRequest[K]) =>
    onChange({ ...value, [k]: v });

  const narrative = policyNarrative(value);

  return (
    <div className="card-warm p-5 space-y-0">
      {label && <p className="kicker mb-4">{label}</p>}

      {/* ── NCT Lookup ───────────────────────────────────────────────────── */}
      <NctLookup onApply={(patch) => onChange({ ...value, ...patch })} />

      {/* ── Policy narrative ─────────────────────────────────────────────── */}
      <div className="mb-5 rounded-lg px-4 py-3" style={{ background: "var(--surface-50)", border: "1px solid var(--border-warm)" }}>
        <p className="text-[11px] font-semibold uppercase tracking-wider mb-1" style={{ color: "var(--ink-400)" }}>POLICY INTERPRETATION</p>
        <p className="text-[13px] leading-relaxed" style={{ color: "var(--ink-700)" }}>{narrative}</p>
        <div className="mt-3 pt-3 grid grid-cols-3 gap-2 text-center" style={{ borderTop: "1px solid var(--border-warm)" }}>
          {[
            { label: "Visits/mo", val: value.visits_per_month ?? 2,    lo: "0.5 = bimonthly\nTypical oncology follow-up", hi: "4 = weekly\nPhase 1 / intensive PK" },
            { label: "Visit hrs",  val: value.visit_duration_hours ?? 1.5, lo: "0.5h = quick check-in\nSelf-report / vitals only", hi: "6h+ = intensive\nIV infusion + PK draws" },
          ].map(({ label, val, lo, hi }) => (
            <div key={label} className="rounded p-2" style={{ background: "var(--surface-100)" }}>
              <p className="text-[10px] font-medium" style={{ color: "var(--ink-500)" }}>{label}</p>
              <p className="text-[15px] font-bold" style={{ color: "var(--ink-800)" }}>{val}</p>
              <p className="text-[10px] mt-0.5 whitespace-pre-line leading-tight" style={{ color: "var(--ink-400)" }}>{val <= (label === "Visits/mo" ? 1 : 1) ? lo : hi}</p>
            </div>
          ))}
          <div className="rounded p-2" style={{ background: "var(--surface-100)" }}>
            <p className="text-[10px] font-medium" style={{ color: "var(--ink-500)" }}>Burden tier</p>
            {(() => {
              const visits = value.visits_per_month ?? 2;
              const hrs    = value.visit_duration_hours ?? 1.5;
              const inv    = value.invasive_procedures && value.invasive_procedures !== "none";
              const score  = [visits >= 3, hrs >= 3, inv, value.ediary_frequency && value.ediary_frequency !== "none"].filter(Boolean).length;
              const tier   = score >= 3 ? ["🔴", "HIGH", "#dc2626"] : score >= 1 ? ["🔵", "MEDIUM", "var(--primary-700)"] : ["🟢", "LOW", "#16a34a"];
              return <>
                <p className="text-[18px]">{tier[0]}</p>
                <p className="text-[11px] font-bold" style={{ color: tier[2] as string }}>{tier[1] as string}</p>
                <p className="text-[10px] mt-0.5 leading-tight" style={{ color: "var(--ink-400)" }}>
                  {score >= 3 ? "Expect high dropout" : score >= 1 ? "Moderate dropout risk" : "Retention-friendly"}
                </p>
              </>;
            })()}
          </div>
        </div>
      </div>

      {/* ── Therapeutic Area ─────────────────────────────────────────────── */}
      <div className="pb-4">
        <Label>Therapeutic Area</Label>
        <select
          value={value.therapeutic_area}
          onChange={(e) => set("therapeutic_area", e.target.value)}
          className="select-warm mt-1 w-full"
        >
          {THERAPEUTIC_AREAS.map((ta) => (
            <option key={ta.value} value={ta.value}>{ta.label}</option>
          ))}
        </select>
        <p className="mt-1 text-[11px]" style={{ color: "var(--ink-400)" }}>
          {THERAPEUTIC_AREAS.find((t) => t.value === value.therapeutic_area)?.ref}
        </p>
      </div>

      {/* ── Trial Scale ───────────────────────────────────────────────────── */}
      <Section title="Trial Scale">
        <div className="grid grid-cols-3 gap-2.5">
          <NumberField label="Patients" value={value.n_patients} min={50} max={5000}
            onChange={(v) => set("n_patients", v)} />
          <NumberField label="Sites" value={value.n_sites} min={1} max={200}
            onChange={(v) => set("n_sites", v)} />
          <NumberField label="Months" value={value.n_rounds} min={6} max={72}
            onChange={(v) => set("n_rounds", v)} />
        </div>
        <div className="mt-3">
          <SliderField
            label="Enrollment rate" value={value.enrollment_rate_modifier ?? 1.0}
            min={0.2} max={3.0} step={0.05}
            format={(v) => `${v.toFixed(2)}×`}
            hint="Multiplier on TA baseline recruitment rate (1.0 = typical)"
            onChange={(v) => set("enrollment_rate_modifier", v)}
          />
        </div>
      </Section>

      {/* ── Visit Schedule ────────────────────────────────────────────────── */}
      <Section title="Visit Schedule">
        <div className="space-y-3.5">
          <SliderField
            label="Visits per month" value={value.visits_per_month ?? 2}
            min={0.5} max={8} step={0.5}
            format={(v) => v < 1 ? `1 / ${Math.round(1/v)} mo` : `${v}/mo`}
            hint="Scheduled clinic visits (0.5 = bimonthly, 4 = weekly)"
            onChange={(v) => set("visits_per_month", v)}
          />
          <SliderField
            label="Visit duration" value={value.visit_duration_hours ?? 1.5}
            min={0.5} max={8} step={0.5}
            format={(v) => `${v}h`}
            hint="Hours per visit including travel, wait, and procedures"
            onChange={(v) => set("visit_duration_hours", v)}
          />
          <SelectField
            label="Invasive procedures"
            value={value.invasive_procedures ?? "none"}
            hint="Most burdensome single procedure at each visit"
            options={[
              { value: "none",     label: "None / questionnaire only" },
              { value: "blood",    label: "Blood draw / PK sampling" },
              { value: "infusion", label: "IV infusion (≥ 1h)" },
              { value: "biopsy",   label: "Tissue / bone marrow biopsy" },
              { value: "lp",       label: "Lumbar puncture / CSF draw" },
            ]}
            onChange={(v) => set("invasive_procedures", v)}
          />
          <SelectField
            label="eDiary / ePRO"
            value={value.ediary_frequency ?? "none"}
            hint="Electronic patient-reported outcome frequency"
            options={[
              { value: "none",   label: "None" },
              { value: "weekly", label: "Weekly" },
              { value: "daily",  label: "Daily" },
            ]}
            onChange={(v) => set("ediary_frequency", v)}
          />
        </div>
      </Section>

      {/* ── Site & Operations ─────────────────────────────────────────────── */}
      <Section title="Site & Operations" defaultOpen={false}>
        <div className="space-y-3.5">
          <Toggle
            label="Risk-based monitoring (RBM)"
            hint="Centralized statistical monitoring vs. traditional on-site SDV"
            checked={value.monitoring_active ?? true}
            onChange={(v) => set("monitoring_active", v)}
          />
          <Toggle
            label="Patient support program"
            hint="Dedicated coordinators, transport reimbursement, and SMS reminders"
            checked={value.patient_support_program ?? false}
            onChange={(v) => set("patient_support_program", v)}
          />
          <SelectField
            label="Site quality variance"
            value={value.site_quality_variance ?? "medium"}
            hint="Spread in site performance — high means some sites will struggle"
            options={[
              { value: "low",    label: "Low — uniform high-performing sites" },
              { value: "medium", label: "Medium — typical multi-centre spread" },
              { value: "high",   label: "High — significant site heterogeneity" },
            ]}
            onChange={(v) => set("site_quality_variance", v)}
          />
        </div>
      </Section>

      {/* ── Randomization & Design ────────────────────────────────────────── */}
      <Section title="Trial Design" defaultOpen={false}>
        <div className="space-y-3.5">
          <SelectField
            label="Randomization ratio"
            value={value.randomization_ratio ?? "1:1"}
            hint="Treatment:placebo allocation ratio"
            options={[
              { value: "1:1", label: "1:1 — equal arms" },
              { value: "2:1", label: "2:1 — 2× treatment" },
              { value: "3:1", label: "3:1 — 3× treatment" },
            ]}
            onChange={(v) => set("randomization_ratio", v)}
          />
          <Toggle
            label="Double-blind"
            hint="Unblinding events increase dropout hazard and belief variance"
            checked={value.blinded ?? true}
            onChange={(v) => set("blinded", v)}
          />
          <SelectField
            label="Competitive landscape"
            value={value.competitive_pressure ?? "none"}
            hint="Rival trials or negative social media events erode patient belief"
            options={[
              { value: "none",   label: "None — uncontested indication" },
              { value: "low",    label: "Low — 1–2 competing trials" },
              { value: "medium", label: "Medium — active recruiting landscape" },
              { value: "high",   label: "High — crowded + media scrutiny" },
            ]}
            onChange={(v) => set("competitive_pressure", v)}
          />
        </div>
      </Section>

      {/* ── Reproducibility ───────────────────────────────────────────────── */}
      <Section title="Reproducibility" defaultOpen={false}>
        <NumberField
          label="Random seed" value={value.seed} min={0} max={999999}
          placeholder="0"
          hint="Same seed → identical run. Change to explore stochastic variance."
          onChange={(v) => set("seed", v ?? 0)}
        />
      </Section>
    </div>
  );
}
