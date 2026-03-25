"use client";

import { useState } from "react";
import { GitCompareArrows, TrendingDown, TrendingUp, Minus } from "lucide-react";
import { AppShell } from "@/components/layout/AppShell";
import { TrialConfigPanel } from "@/components/simulation/TrialConfigPanel";
import { ScrambleText } from "@/components/ui/ScrambleText";
import { AnimatedCounter } from "@/components/ui/AnimatedCounter";
import { compare, SimulateRequest, SimulateResponse } from "@/lib/api";
import {
  ComposedChart, Line, Area, CartesianGrid, ResponsiveContainer,
  Tooltip, XAxis, YAxis, Legend, ReferenceLine,
} from "recharts";

const DEFAULT_A: SimulateRequest = {
  therapeutic_area: "cns",
  visits_per_month: 1, visit_duration_hours: 1, invasive_procedures: "blood",
};
const DEFAULT_B: SimulateRequest = {
  therapeutic_area: "cns",
  visits_per_month: 4, visit_duration_hours: 4, invasive_procedures: "lp",
};

const TOOLTIP_STYLE = {
  background: "var(--surface-50)", border: "1px solid var(--border-warm)",
  borderRadius: 10, fontSize: 11, color: "var(--ink-900)", boxShadow: "var(--shadow-card)",
};

// ── Delta row ─────────────────────────────────────────────────────────────────

interface DeltaEntry { label: string; aVal: number; bVal: number; higherGood: boolean; fmt: (v: number) => string }

function DeltaRow({ d }: { d: DeltaEntry }) {
  const diff = d.bVal - d.aVal;
  const good = diff === 0 ? null : (diff > 0) === d.higherGood;
  const color = good === null ? "var(--ink-400)" : good ? "var(--success)" : "var(--danger)";
  const Icon = diff === 0 ? Minus : diff > 0 ? TrendingUp : TrendingDown;

  return (
    <tr style={{ borderBottom: "1px solid var(--border-warm)" }}>
      <td className="py-2.5 pr-4 text-xs" style={{ color: "var(--ink-500)" }}>{d.label}</td>
      <td className="py-2.5 pr-4 text-sm font-mono text-center" style={{ color: "var(--ink-900)" }}>{d.fmt(d.aVal)}</td>
      <td className="py-2.5 pr-4 text-sm font-mono text-center" style={{ color: "var(--ink-900)" }}>{d.fmt(d.bVal)}</td>
      <td className="py-2.5 text-sm font-mono font-semibold text-center">
        <span className="inline-flex items-center gap-1" style={{ color }}>
          <Icon size={12} />
          {diff === 0 ? "—" : `${diff > 0 ? "+" : ""}${d.fmt(Math.abs(diff))}`}
        </span>
      </td>
    </tr>
  );
}

function buildDeltas(a: SimulateResponse, b: SimulateResponse): DeltaEntry[] {
  const fa = a.round_snapshots.at(-1)!;
  const fb = b.round_snapshots.at(-1)!;
  const nA = fa.n_dropout + fa.n_completed + fa.n_enrolled;
  const nB = fb.n_dropout + fb.n_completed + fb.n_enrolled;
  const p = (v: number) => `${v.toFixed(1)}%`;
  return [
    { label: "Dropout (enrolled)",  aVal: nA > 0 ? fa.n_dropout / nA * 100 : 0,         bVal: nB > 0 ? fb.n_dropout / nB * 100 : 0,         higherGood: false, fmt: p },
    { label: "Final Adherence",     aVal: fa.mean_adherence * 100,                       bVal: fb.mean_adherence * 100,                       higherGood: true,  fmt: p },
    { label: "Safety Signal",       aVal: fa.safety_signal * 100,                        bVal: fb.safety_signal * 100,                        higherGood: false, fmt: p },
    { label: "Data Quality",        aVal: fa.data_quality * 100,                         bVal: fb.data_quality * 100,                         higherGood: true,  fmt: p },
    { label: "Visit Compliance",    aVal: fa.visit_compliance_rate * 100,                bVal: fb.visit_compliance_rate * 100,                higherGood: true,  fmt: p },
    { label: "Mean Belief",         aVal: fa.mean_belief * 100,                          bVal: fb.mean_belief * 100,                          higherGood: true,  fmt: p },
  ];
}

// ── Overlay chart ─────────────────────────────────────────────────────────────

function OverlayChart({
  dataA, dataB,
  metricA, metricB,
  title, sublabel,
}: {
  dataA: Record<string, unknown>[];
  dataB: Record<string, unknown>[];
  metricA: string;
  metricB: string;
  title: string;
  sublabel: string;
}) {
  const merged = dataA.map((row, i) => ({
    ...row,
    [metricB]: (dataB[i] as Record<string, unknown>)?.[metricA],
  }));

  return (
    <div className="card-warm p-4">
      <p className="kicker text-[11px] mb-0.5">{title}</p>
      <p className="text-xs mb-3" style={{ color: "var(--ink-400)" }}>{sublabel}</p>
      <ResponsiveContainer width="100%" height={180}>
        <ComposedChart data={merged} margin={{ top: 4, right: 4, bottom: 0, left: -20 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--border-warm)" />
          <XAxis dataKey="month" tick={{ fontSize: 9, fill: "var(--ink-400)" }} tickFormatter={(v) => `${v}mo`} />
          <YAxis tick={{ fontSize: 9, fill: "var(--ink-400)" }} tickFormatter={(v) => `${v}%`} />
          <Tooltip contentStyle={TOOLTIP_STYLE} labelFormatter={(v) => `Month ${v}`} />
          <Legend wrapperStyle={{ fontSize: 10, color: "var(--ink-500)", paddingTop: 4 }} />
          <Area type="monotone" dataKey={metricA} fill="rgba(7,160,195,0.06)" stroke="none" />
          <Line type="monotone" dataKey={metricA} name="Scenario A" stroke="var(--primary-700)" dot={false} strokeWidth={2} />
          <Line type="monotone" dataKey={metricB} name="Scenario B" stroke="var(--chart-enforcement)" dot={false} strokeWidth={2} strokeDasharray="4 3" />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}

function toRows(result: SimulateResponse) {
  return result.round_snapshots.map((s) => ({
    month:          s.time_months,
    dropout:        +((s.n_dropout / Math.max(s.n_dropout + s.n_completed + s.n_enrolled, 1)) * 100).toFixed(1),
    adherence:      +(s.mean_adherence * 100).toFixed(1),
    visitCompliance:+(s.visit_compliance_rate * 100).toFixed(1),
    safety:         +(s.safety_signal * 100).toFixed(1),
    dataQuality:    +(s.data_quality * 100).toFixed(1),
    belief:         +(s.mean_belief * 100).toFixed(1),
    active_sites:   s.active_sites,
  }));
}

// ── Site Activation Comparison ────────────────────────────────────────────────

function SiteActivationComparison({
  resultA, resultB,
}: { resultA: SimulateResponse; resultB: SimulateResponse }) {
  const hasDataA = resultA.round_snapshots.some((s) => s.active_sites != null);
  const hasDataB = resultB.round_snapshots.some((s) => s.active_sites != null);

  if (!hasDataA && !hasDataB) {
    return (
      <div className="card-warm p-5">
        <p className="kicker text-[11px] mb-1">Site Activation Comparison</p>
        <p className="text-xs" style={{ color: "var(--ink-400)" }}>
          No site activation data available — re-run simulations to see the site ramp-up curves here.
        </p>
      </div>
    );
  }

  const rowsA = resultA.round_snapshots
    .filter((s) => s.active_sites != null)
    .map((s) => ({ month: s.time_months, activeSitesA: s.active_sites as number }));

  const rowsB = resultB.round_snapshots
    .filter((s) => s.active_sites != null)
    .map((s) => ({ month: s.time_months, activeSitesB: s.active_sites as number }));

  // Merge by month index
  const maxLen = Math.max(rowsA.length, rowsB.length);
  const merged = Array.from({ length: maxLen }, (_, i) => ({
    month:        rowsA[i]?.month ?? rowsB[i]?.month ?? i + 1,
    activeSitesA: rowsA[i]?.activeSitesA,
    activeSitesB: rowsB[i]?.activeSitesB,
  }));

  const nSitesA = resultA.n_sites;
  const nSitesB = resultB.n_sites;
  const maxSites = Math.max(nSitesA, nSitesB);

  return (
    <div className="card-warm p-4">
      <p className="kicker text-[11px] mb-0.5">Site Activation Comparison</p>
      <p className="text-xs mb-3" style={{ color: "var(--ink-400)" }}>
        Site ramp-up curves — A vs B (NCI median activation: 167 days / ~5.6 months)
      </p>
      <ResponsiveContainer width="100%" height={200}>
        <ComposedChart data={merged} margin={{ top: 4, right: 20, bottom: 0, left: -20 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--border-warm)" />
          <XAxis dataKey="month" tick={{ fontSize: 9, fill: "var(--ink-400)" }} tickFormatter={(v) => `${v}mo`} />
          <YAxis
            domain={[0, maxSites]}
            tick={{ fontSize: 9, fill: "var(--ink-400)" }}
            tickFormatter={(v) => String(Math.round(v))}
          />
          <Tooltip contentStyle={TOOLTIP_STYLE} labelFormatter={(v) => `Month ${v}`}
            formatter={(v: number, name: string) => [
              `${Math.round(v)} sites`,
              name === "activeSitesA" ? "Scenario A" : "Scenario B",
            ]}
          />
          <Legend
            wrapperStyle={{ fontSize: 10, color: "var(--ink-500)", paddingTop: 4 }}
            formatter={(value) => value === "activeSitesA" ? "Scenario A" : "Scenario B"}
          />
          {hasDataA && nSitesA !== nSitesB && (
            <ReferenceLine y={nSitesA} strokeDasharray="3 3" stroke="rgba(7,160,195,0.3)" strokeWidth={1} />
          )}
          <ReferenceLine y={maxSites} strokeDasharray="4 3" stroke="var(--ink-300)" strokeWidth={1.5} />
          {hasDataA && (
            <Line type="monotone" dataKey="activeSitesA" name="activeSitesA"
              stroke="var(--primary-700)" dot={false} strokeWidth={2} connectNulls />
          )}
          {hasDataB && (
            <Line type="monotone" dataKey="activeSitesB" name="activeSitesB"
              stroke="var(--chart-enforcement)" dot={false} strokeWidth={2}
              strokeDasharray="4 3" connectNulls />
          )}
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function ComparePage() {
  const [reqA, setReqA] = useState<SimulateRequest>(DEFAULT_A);
  const [reqB, setReqB] = useState<SimulateRequest>(DEFAULT_B);
  const [resultA, setResultA] = useState<SimulateResponse | null>(null);
  const [resultB, setResultB] = useState<SimulateResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error,   setError]   = useState<string | null>(null);

  async function run() {
    setLoading(true);
    setError(null);
    try {
      const res = await compare(reqA, reqB);
      setResultA(res.scenario_a);
      setResultB(res.scenario_b);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }

  const deltas = resultA && resultB ? buildDeltas(resultA, resultB) : null;
  const rowsA  = resultA ? toRows(resultA) : [];
  const rowsB  = resultB ? toRows(resultB) : [];

  return (
    <AppShell>
      <div className="mx-auto max-w-[1560px] px-4 py-6 lg:px-8">
        <div className="mb-6">
          <h1 className="text-3xl font-bold" style={{ color: "var(--ink-900)", letterSpacing: "-0.03em" }}>
            <ScrambleText text="Scenario Comparison" duration={800} delay={60} />
          </h1>
          <p className="mt-1.5 text-sm" style={{ color: "var(--ink-400)" }}>
            Run two trial configurations head-to-head and inspect metric deltas.
          </p>
        </div>

        {/* Config forms */}
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 mb-4">
          <TrialConfigPanel value={reqA} onChange={setReqA} label="Scenario A" />
          <TrialConfigPanel value={reqB} onChange={setReqB} label="Scenario B" />
        </div>

        {/* Compare button */}
        <button
          onClick={run}
          disabled={loading}
          className="btn-primary w-full py-3 text-base mb-4"
        >
          {loading ? (
            <>
              <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24" fill="none">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
              Running comparison…
            </>
          ) : (
            <>
              <GitCompareArrows size={16} />
              Compare scenarios
            </>
          )}
        </button>

        {error && (
          <div className="rounded-xl border px-3 py-2.5 text-sm mb-4"
            style={{ color: "var(--danger)", borderColor: "rgba(220,38,38,0.2)", background: "#fef2f2" }}>
            {error}
          </div>
        )}

        {deltas && resultA && resultB && (
          <div className="space-y-4" style={{ animation: "fadeIn 320ms ease both" }}>
            {/* Delta table */}
            <div className="card-raised p-5">
              <p className="kicker text-[11px] mb-3">Metric Delta (B − A)</p>
              <table className="w-full">
                <thead>
                  <tr style={{ borderBottom: "1px solid var(--border-warm)" }}>
                    {["Metric", "Scenario A", "Scenario B", "Δ (B−A)"].map((h) => (
                      <th key={h} className="pb-2 text-left text-xs font-semibold" style={{ color: "var(--ink-400)" }}>
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {deltas.map((d) => <DeltaRow key={d.label} d={d} />)}
                </tbody>
              </table>
            </div>

            {/* Overlay charts */}
            <div className="grid grid-cols-2 gap-3">
              <OverlayChart dataA={rowsA} dataB={rowsB} metricA="dropout"    metricB="dropoutB"    title="Dropout"            sublabel="Fraction of ever-enrolled" />
              <OverlayChart dataA={rowsA} dataB={rowsB} metricA="adherence"  metricB="adherenceB"  title="Adherence"          sublabel="Protocol adherence rate" />
              <OverlayChart dataA={rowsA} dataB={rowsB} metricA="safety"     metricB="safetyB"     title="Safety Signal"      sublabel="Cumulative safety signal" />
              <OverlayChart dataA={rowsA} dataB={rowsB} metricA="dataQuality" metricB="dataQualityB" title="Data Quality"     sublabel="CRF completeness & accuracy" />
            </div>

            {/* Site activation comparison */}
            <SiteActivationComparison resultA={resultA} resultB={resultB} />

            {/* Runtime footnote */}
            <div className="card-warm px-5 py-3 flex items-center justify-between text-xs" style={{ color: "var(--ink-400)" }}>
              <span>Scenario A: <span className="metric-num font-semibold" style={{ color: "var(--ink-900)" }}>{resultA.elapsed_ms.toFixed(0)}ms</span></span>
              <span>Scenario B: <span className="metric-num font-semibold" style={{ color: "var(--ink-900)" }}>{resultB.elapsed_ms.toFixed(0)}ms</span></span>
              <span>
                ASSUMED outputs: A=<span className="font-semibold" style={{ color: "var(--ink-700)" }}>{resultA.assumed_count}</span>{" "}
                B=<span className="font-semibold" style={{ color: "var(--ink-700)" }}>{resultB.assumed_count}</span>
              </span>
            </div>
          </div>
        )}
      </div>
    </AppShell>
  );
}
