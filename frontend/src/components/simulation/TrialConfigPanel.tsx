"use client";

import { useState } from "react";
import { ChevronDown, ChevronUp } from "lucide-react";
import { THERAPEUTIC_AREAS, SimulateRequest } from "@/lib/api";

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
        <span className="text-xs font-semibold font-mono" style={{ color: "var(--crimson-700)" }}>
          {format(value)}
        </span>
      </div>
      <input
        type="range" min={min} max={max} step={step} value={value}
        onChange={(e) => onChange(parseFloat(e.target.value))}
        className="w-full accent-[var(--crimson-700)] h-1.5 cursor-pointer"
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
          style={{ background: checked ? "var(--crimson-700)" : "var(--cream-400)" }} />
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

      {/* ── Policy narrative ─────────────────────────────────────────────── */}
      <div className="mb-5 rounded-lg px-4 py-3" style={{ background: "var(--cream-100)", border: "1px solid var(--cream-300)" }}>
        <p className="text-[11px] font-semibold uppercase tracking-wider mb-1" style={{ color: "var(--ink-400)" }}>POLICY INTERPRETATION</p>
        <p className="text-[13px] leading-relaxed" style={{ color: "var(--ink-700)" }}>{narrative}</p>
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
