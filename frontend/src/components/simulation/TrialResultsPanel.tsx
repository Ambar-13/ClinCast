"use client";

import { useEffect, useState } from "react";
import {
  Area, ComposedChart, Line, CartesianGrid,
  ResponsiveContainer, Tooltip, XAxis, YAxis, Legend,
  ScatterChart, Scatter, Cell, ReferenceLine,
} from "recharts";
import { AnimatedCounter } from "@/components/ui/AnimatedCounter";
import { SimulateResponse, RoundSnapshot, SwarmMetadata } from "@/lib/api";

// ── Helpers ───────────────────────────────────────────────────────────────────

function pct(v: number) { return `${v.toFixed(1)}%`; }

interface ChartRow {
  month: number;
  dropout: number;
  adherence: number;
  visitCompliance: number;
  safety: number;
  dataQuality: number;
  belief: number;
  nEnrolled: number;
}

function toRows(snaps: RoundSnapshot[]): ChartRow[] {
  return snaps.map((s) => ({
    month:          s.time_months,
    dropout:        +((s.n_dropout / Math.max(s.n_dropout + s.n_completed + s.n_enrolled, 1)) * 100).toFixed(1),
    adherence:      +(s.mean_adherence   * 100).toFixed(1),
    visitCompliance:+(s.visit_compliance_rate * 100).toFixed(1),
    safety:         +(s.safety_signal    * 100).toFixed(1),
    dataQuality:    +(s.data_quality     * 100).toFixed(1),
    belief:         +(s.mean_belief      * 100).toFixed(1),
    nEnrolled:      s.n_enrolled,
  }));
}

// ── Shared chart wrapper ──────────────────────────────────────────────────────

const TOOLTIP_STYLE = {
  background: "var(--cream-100)",
  border:     "1px solid var(--border-warm)",
  borderRadius: 10,
  fontSize:   11,
  color:      "var(--ink-900)",
  boxShadow:  "var(--shadow-card)",
};

function MetricChart({
  data,
  title,
  sublabel,
  lines,
  yDomain = [0, 100],
  yTickFmt = (v: number) => `${v}%`,
}: {
  data: ChartRow[];
  title: string;
  sublabel: string;
  lines: { key: string; color: string; name: string }[];
  yDomain?: [number | "auto", number | "auto"];
  yTickFmt?: (v: number) => string;
}) {
  return (
    <div className="card-warm p-4">
      <p className="kicker text-[10px] mb-0.5">{title}</p>
      <p className="text-[11px] mb-3" style={{ color: "var(--ink-400)" }}>{sublabel}</p>
      <ResponsiveContainer width="100%" height={180}>
        <ComposedChart data={data} margin={{ top: 4, right: 4, bottom: 0, left: -20 }}>
          <defs>
            {lines.map((l) => (
              <linearGradient key={l.key} id={`grad-${l.key}`} x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%"  stopColor={l.color} stopOpacity={0.15} />
                <stop offset="95%" stopColor={l.color} stopOpacity={0}    />
              </linearGradient>
            ))}
          </defs>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--border-warm)" />
          <XAxis
            dataKey="month"
            tick={{ fontSize: 9, fill: "var(--ink-400)" }}
            tickFormatter={(v) => `${v}mo`}
          />
          <YAxis
            domain={yDomain}
            tick={{ fontSize: 9, fill: "var(--ink-400)" }}
            tickFormatter={yTickFmt}
          />
          <Tooltip
            contentStyle={TOOLTIP_STYLE}
            labelFormatter={(v) => `Month ${v}`}
          />
          <Legend
            wrapperStyle={{ fontSize: 10, color: "var(--ink-500)", paddingTop: 4 }}
          />
          {lines.map((l, i) => (
            <>
              {i === 0 && (
                <Area
                  key={`area-${l.key}`}
                  type="monotone"
                  dataKey={l.key}
                  fill={`url(#grad-${l.key})`}
                  stroke="none"
                />
              )}
              <Line
                key={l.key}
                type="monotone"
                dataKey={l.key}
                name={l.name}
                stroke={l.color}
                dot={false}
                strokeWidth={2}
              />
            </>
          ))}
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}

// ── KPI strip ─────────────────────────────────────────────────────────────────

function KpiCard({ label, value, sub, color }: { label: string; value: number; sub?: string; color?: string }) {
  return (
    <div className="card-warm p-4 text-center">
      <p className="kicker text-[10px] mb-2">{label}</p>
      <p
        className="metric-num text-2xl font-bold"
        style={{ color: color ?? "var(--ink-900)", letterSpacing: "-0.03em" }}
      >
        <AnimatedCounter value={value} formatter={(v) => `${v.toFixed(1)}%`} />
      </p>
      {sub && <p className="mt-1 text-[11px]" style={{ color: "var(--ink-400)" }}>{sub}</p>}
    </div>
  );
}

// ── Epistemic provenance ──────────────────────────────────────────────────────

function ProvenanceStrip({ result }: { result: SimulateResponse }) {
  return (
    <div className="card-warm p-5">
      <p className="kicker text-[10px] mb-3">Epistemic Provenance</p>
      <div className="space-y-2 text-xs">
        {[
          { cls: "font-semibold", style: { color: "var(--success)" },  tag: "GROUNDED",    desc: "Directly fitted to published figures" },
          { cls: "font-semibold", style: { color: "var(--warning)" },  tag: "DIRECTIONAL", desc: "Direction supported; magnitude estimated" },
          { cls: "font-semibold", style: { color: "var(--danger)" },   tag: "ASSUMED",     desc: "No empirical anchor — sweep recommended" },
        ].map(({ cls, style, tag, desc }) => (
          <div key={tag} className="flex items-center gap-4">
            <span className={`${cls} font-mono text-[10px] w-24 flex-shrink-0`} style={style}>{tag}</span>
            <span style={{ color: "var(--ink-500)" }}>{desc}</span>
          </div>
        ))}
      </div>
      <div
        className="mt-3 pt-3 text-[11px]"
        style={{ borderTop: "1px solid var(--border-warm)", color: "var(--ink-500)" }}
      >
        <span className="font-semibold" style={{ color: "var(--ink-900)" }}>{result.assumed_count}</span>
        {" "}ASSUMED outputs in this run.
        {result.warnings.length > 0 && (
          <span className="ml-3" style={{ color: "var(--danger)" }}>
            {result.warnings.join(" · ")}
          </span>
        )}
      </div>
    </div>
  );
}

// ── Swarm panel ───────────────────────────────────────────────────────────────

function ShiftBar({ p10, p50, p90, mean, max }: { p10: number; p50: number; p90: number; mean: number; max: number }) {
  const scale = (v: number) => ((v + max) / (2 * max)) * 100;
  return (
    <div className="relative h-5 rounded-full overflow-hidden" style={{ background: "var(--cream-300)" }}>
      <div className="absolute top-0 bottom-0 rounded-full"
        style={{ left: `${scale(p10)}%`, width: `${scale(p90) - scale(p10)}%`, background: "rgba(139,26,26,0.15)" }} />
      <div className="absolute top-1 bottom-1 w-0.5 rounded-full"
        style={{ left: `${scale(p50)}%`, background: "var(--crimson-700)" }} />
      <div className="absolute top-1.5 bottom-1.5 w-1.5 rounded-full"
        style={{ left: `calc(${scale(mean)}% - 3px)`, background: "var(--ink-700)" }} />
      <div className="absolute top-0 bottom-0 w-px opacity-30"
        style={{ left: "50%", background: "var(--ink-500)" }} />
    </div>
  );
}

// Quadrant: belief_shift (Y) vs adherence_shift (X)
// Q1 (+,+) optimistic  Q2 (-,+) motivated skeptic
// Q4 (+,-) trusting    Q3 (-,-) disengaged
const QUADRANT = {
  pp: { color: "#16a34a", bg: "rgba(22,163,74,0.08)",  label: "Optimistic & engaged"  },
  np: { color: "#2563eb", bg: "rgba(37,99,235,0.08)",  label: "Motivated skeptic"      },
  pn: { color: "#d97706", bg: "rgba(217,119,6,0.08)",  label: "Trusting but fatigued"  },
  nn: { color: "#dc2626", bg: "rgba(220,38,38,0.08)",  label: "Skeptical & disengaged" },
};

function quadrantKey(b: number, a: number): keyof typeof QUADRANT {
  if (b >= 0 && a >= 0) return "pp";
  if (b <  0 && a >= 0) return "np";
  if (b >= 0 && a <  0) return "pn";
  return "nn";
}

function SwarmScatter({ votes, totalAgents }: { votes: SwarmMetadata["votes"]; totalAgents: number }) {
  // LLMs round shifts to 0.05 steps → dots stack. Apply deterministic jitter
  // so every agent is individually visible. Jitter spread scales with N so
  // 500+ dots don't overlap as badly.
  const n = votes.length;
  const JITTER = n > 100 ? 1.2 : 0.55;
  const jx = (i: number) => (((i * 7) % 11) - 5) * JITTER;
  const jy = (i: number) => (((i * 3) % 13) - 6) * JITTER;

  const data = votes.map((v, i) => ({
    x: +(v.adherence_shift * 100 + jx(i)).toFixed(2),
    y: +(v.belief_shift    * 100 + jy(i)).toFixed(2),
    rawX: +(v.adherence_shift * 100).toFixed(1),
    rawY: +(v.belief_shift    * 100).toFixed(1),
    label: v.label ?? v.persona ?? "",
    reasoning: v.reasoning ?? "",
    qk: quadrantKey(v.belief_shift, v.adherence_shift),
    idx: i,
  }));

  // Smaller dots when there are many agents so the scatter doesn't become noise
  const dotR = n > 500 ? 3 : n > 100 ? 4.5 : 7;
  const dotOpacity = n > 500 ? 0.55 : n > 100 ? 0.70 : 0.85;

  const CustomDot = (props: { cx?: number; cy?: number; payload?: typeof data[0] }) => {
    const { cx = 0, cy = 0, payload } = props;
    if (!payload) return null;
    const q = QUADRANT[payload.qk];
    return (
      <circle cx={cx} cy={cy} r={dotR}
        fill={q.color} fillOpacity={dotOpacity}
        stroke="white" strokeWidth={dotR > 5 ? 1.5 : 0.5} />
    );
  };

  const CustomTooltip = ({ active, payload }: { active?: boolean; payload?: { payload: typeof data[0] }[] }) => {
    if (!active || !payload?.length) return null;
    const d = payload[0].payload;
    const q = QUADRANT[d.qk];
    const fmt = (v: number) => `${v >= 0 ? "+" : ""}${v.toFixed(1)}%`;
    return (
      <div className="rounded-xl border p-3 max-w-[280px] text-[11px] shadow-lg"
        style={{ background: "var(--cream-100)", borderColor: "var(--border-warm)", color: "var(--ink-700)" }}>
        <div className="flex items-center gap-1.5 mb-2">
          <span className="w-2 h-2 rounded-full flex-shrink-0" style={{ background: q.color }} />
          <span className="font-semibold text-[10px] uppercase tracking-wider" style={{ color: q.color }}>{q.label}</span>
        </div>
        <p className="leading-4 mb-2" style={{ color: "var(--ink-600)" }}>{d.label}</p>
        {d.reasoning && (
          <p className="italic leading-4 mb-2" style={{ color: "var(--ink-500)" }}>"{d.reasoning}"</p>
        )}
        <div className="flex gap-3 font-mono text-[10px] pt-1.5 border-t" style={{ borderColor: "var(--border-warm)" }}>
          <span style={{ color: d.rawY >= 0 ? "#16a34a" : "#dc2626" }}>Belief {fmt(d.rawY)}</span>
          <span style={{ color: d.rawX >= 0 ? "#16a34a" : "#dc2626" }}>Adherence {fmt(d.rawX)}</span>
        </div>
      </div>
    );
  };

  return (
    <div className="rounded-xl border overflow-hidden" style={{ background: "var(--cream-200)", borderColor: "var(--border-warm)" }}>
      <div className="px-4 pt-3 pb-1 flex items-center justify-between">
        <p className="kicker text-[10px]">Agent Decision Map <span className="normal-case font-normal" style={{ color: "var(--ink-400)" }}>({n.toLocaleString()} of {totalAgents.toLocaleString()} agents)</span></p>
        <p className="text-[10px]" style={{ color: "var(--ink-400)" }}>Hover for persona + reasoning</p>
      </div>
      {/* Quadrant legend */}
      <div className="px-4 pb-2 flex flex-wrap gap-x-4 gap-y-1">
        {(Object.values(QUADRANT)).map((q) => (
          <div key={q.label} className="flex items-center gap-1.5">
            <span className="w-2 h-2 rounded-full flex-shrink-0" style={{ background: q.color }} />
            <span className="text-[10px]" style={{ color: "var(--ink-500)" }}>{q.label}</span>
          </div>
        ))}
      </div>
      <ResponsiveContainer width="100%" height={260}>
        <ScatterChart margin={{ top: 8, right: 20, bottom: 20, left: 8 }}>
          {/* Quadrant backgrounds */}
          <defs>
            {(Object.entries(QUADRANT) as [keyof typeof QUADRANT, typeof QUADRANT[keyof typeof QUADRANT]][]).map(([k, q]) => (
              <linearGradient key={k} id={`qbg-${k}`} x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={q.color} stopOpacity={0.05} />
                <stop offset="100%" stopColor={q.color} stopOpacity={0.02} />
              </linearGradient>
            ))}
          </defs>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--border-warm)" />
          <XAxis
            type="number" dataKey="x" name="Adherence Shift"
            domain={[-12, 12]} tick={{ fontSize: 9, fill: "var(--ink-400)" }}
            tickFormatter={(v) => `${v > 0 ? "+" : ""}${v}%`}
            label={{ value: "Adherence shift →", position: "insideBottom", offset: -10, fontSize: 9, fill: "var(--ink-400)" }}
          />
          <YAxis
            type="number" dataKey="y" name="Belief Shift"
            domain={[-17, 17]} tick={{ fontSize: 9, fill: "var(--ink-400)" }}
            tickFormatter={(v) => `${v > 0 ? "+" : ""}${v}%`}
            label={{ value: "Belief shift", angle: -90, position: "insideLeft", offset: 10, fontSize: 9, fill: "var(--ink-400)" }}
          />
          <ReferenceLine x={0} stroke="var(--ink-300)" strokeWidth={1.5} />
          <ReferenceLine y={0} stroke="var(--ink-300)" strokeWidth={1.5} />
          <Tooltip content={<CustomTooltip />} cursor={{ strokeDasharray: "3 3", stroke: "var(--ink-300)" }} />
          <Scatter data={data} shape={<CustomDot />}>
            {data.map((entry, i) => (
              <Cell key={i} fill={QUADRANT[entry.qk].color} />
            ))}
          </Scatter>
        </ScatterChart>
      </ResponsiveContainer>
    </div>
  );
}

function SwarmPanel({ meta }: { meta: SwarmMetadata }) {
  if (meta.swarm_error) {
    return (
      <div className="card-tinted p-4 text-xs" style={{ color: "var(--danger)" }}>
        Swarm elicitation failed: {meta.swarm_error}
      </div>
    );
  }
  const fmt = (v: number) => `${v >= 0 ? "+" : ""}${(v * 100).toFixed(1)}%`;
  return (
    <div className="card-warm p-5 space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <p className="kicker text-[10px]">Swarm Elicitation</p>
          <span className="rounded-full px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-widest"
            style={{ background: "rgba(245,158,11,0.12)", color: "#b45309", border: "1px solid rgba(245,158,11,0.25)" }}>
            SWARM-ELICITED
          </span>
        </div>
        <p className="text-[11px]" style={{ color: "var(--ink-400)" }}>
          <span className="metric-num font-semibold" style={{ color: "var(--ink-900)" }}>{meta.n_agents?.toLocaleString()}</span> agents
          {meta.n_failed > 0 && <span style={{ color: "var(--warning)" }}> · {meta.n_failed} failed</span>}
        </p>
      </div>

      {/* Summary KPIs */}
      <div className="grid grid-cols-2 gap-3">
        {[
          { label: "Belief Shift",    mean: meta.belief_shift,    std: meta.belief_std,    p10: meta.belief_p10,    p50: meta.belief_p50,    p90: meta.belief_p90,    max: 0.15 },
          { label: "Adherence Shift", mean: meta.adherence_shift, std: meta.adherence_std, p10: meta.adherence_p10, p50: meta.adherence_p50, p90: meta.adherence_p90, max: 0.10 },
        ].map(({ label, mean, std, p10, p50, p90, max }) => (
          <div key={label} className="rounded-xl border p-3" style={{ background: "var(--cream-200)", borderColor: "var(--border-warm)" }}>
            <p className="kicker text-[10px] mb-2">{label}</p>
            <p className="metric-num text-xl font-bold mb-1" style={{ color: mean >= 0 ? "var(--success)" : "var(--danger)" }}>
              {fmt(mean)}
            </p>
            <p className="text-[10px] mb-2" style={{ color: "var(--ink-400)" }}>
              σ={fmt(std)} · p10={fmt(p10)} · p90={fmt(p90)}
            </p>
            <ShiftBar p10={p10} p50={p50} p90={p90} mean={mean} max={max} />
          </div>
        ))}
      </div>

      {/* Scatter chart */}
      {meta.votes?.length > 0 && <SwarmScatter votes={meta.votes} totalAgents={meta.n_agents} />}

      {/* Agent cards — cap at 20 cards; scatter shows the full distribution */}
      {meta.votes?.length > 0 && (
        <div>
          <p className="kicker text-[10px] mb-3">
            Representative Agents (showing {Math.min(meta.votes.length, 20)} of {meta.n_agents?.toLocaleString()} — full distribution above)
          </p>
          <div className="space-y-2">
            {meta.votes.slice(0, 20).map((v, i) => {
              const qk = quadrantKey(v.belief_shift, v.adherence_shift);
              const q  = QUADRANT[qk];
              return (
                <div key={i} className="rounded-xl border p-3"
                  style={{ borderColor: "var(--border-warm)", background: "var(--cream-100)" }}>
                  {/* Header row */}
                  <div className="flex items-start justify-between gap-3 mb-2">
                    <div className="flex items-start gap-2 min-w-0">
                      <span className="mt-0.5 w-2.5 h-2.5 rounded-full flex-shrink-0" style={{ background: q.color }} />
                      <p className="text-[11px] leading-4" style={{ color: "var(--ink-700)" }}>
                        {v.label ?? v.persona ?? `Agent ${i + 1}`}
                      </p>
                    </div>
                    <div className="flex gap-2.5 flex-shrink-0 font-mono text-[10px]">
                      <span className="rounded px-1.5 py-0.5"
                        style={{ background: v.belief_shift >= 0 ? "rgba(22,163,74,0.10)" : "rgba(220,38,38,0.10)",
                                 color: v.belief_shift >= 0 ? "#16a34a" : "#dc2626" }}>
                        B {fmt(v.belief_shift)}
                      </span>
                      <span className="rounded px-1.5 py-0.5"
                        style={{ background: v.adherence_shift >= 0 ? "rgba(22,163,74,0.10)" : "rgba(220,38,38,0.10)",
                                 color: v.adherence_shift >= 0 ? "#16a34a" : "#dc2626" }}>
                        A {fmt(v.adherence_shift)}
                      </span>
                    </div>
                  </div>
                  {/* Reasoning */}
                  {v.reasoning && (
                    <p className="text-[11px] italic leading-4 pl-4.5"
                      style={{ color: "var(--ink-500)", paddingLeft: "18px" }}>
                      "{v.reasoning}"
                    </p>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}

// ── Main panel ────────────────────────────────────────────────────────────────

interface Props {
  result: SimulateResponse;
}

export function TrialResultsPanel({ result }: Props) {
  const [ready, setReady] = useState(false);
  useEffect(() => {
    const id = requestAnimationFrame(() => setReady(true));
    return () => cancelAnimationFrame(id);
  }, []);

  const rows = toRows(result.round_snapshots);
  const final = result.round_snapshots.at(-1)!;

  // Dropout: use total ever-enrolled (dropout + completed; n_enrolled is currently active)
  const nEver = final.n_dropout + final.n_completed + final.n_enrolled;
  const dropoutPct = nEver > 0 ? (final.n_dropout / nEver) * 100 : 0;

  // Adherence & belief: use last round with active patients — final round often has 0 enrolled
  const lastActive = [...result.round_snapshots].reverse().find(s => s.n_enrolled > 0) ?? final;
  // Time-weighted mean adherence across all active rounds
  const activeSnaps = result.round_snapshots.filter(s => s.n_enrolled > 0);
  const adherencePct = activeSnaps.length > 0
    ? activeSnaps.reduce((sum, s) => sum + s.mean_adherence * s.n_enrolled, 0) /
      activeSnaps.reduce((sum, s) => sum + s.n_enrolled, 0) * 100
    : 0;
  const safetyPct = final.safety_signal * 100;
  const dqPct = final.data_quality * 100;

  return (
    <div className="space-y-4" style={{ animation: "fadeIn 320ms ease both" }}>
      {/* KPI strip */}
      <div className="grid grid-cols-4 gap-3">
        <KpiCard label="Dropout (enrolled)" value={dropoutPct} color="var(--danger)"   sub="fraction discontinued" />
        <KpiCard label="Mean Adherence" value={adherencePct} color="var(--success)" sub="enrollment-weighted" />
        <KpiCard label="Safety Signal"      value={safetyPct}  color="var(--warning)"  />
        <KpiCard label="Data Quality"       value={dqPct}      color="var(--crimson-700)" />
      </div>

      {/* Charts */}
      {ready ? (
        <div className="grid grid-cols-2 gap-3">
          <MetricChart
            data={rows}
            title="Dropout"
            sublabel="Fraction of ever-enrolled patients"
            lines={[{ key: "dropout", color: "var(--danger)", name: "Dropout %" }]}
          />
          <MetricChart
            data={rows}
            title="Adherence & Visit Compliance"
            sublabel="Protocol adherence over trial duration"
            lines={[
              { key: "adherence",       color: "var(--success)",      name: "Adherence" },
              { key: "visitCompliance", color: "var(--crimson-700)", name: "Visit Compliance" },
            ]}
          />
          <MetricChart
            data={rows}
            title="Enrollment"
            sublabel="Active patients per month"
            yDomain={[0, "auto"]}
            yTickFmt={(v) => String(Math.round(v))}
            lines={[{ key: "nEnrolled", color: "var(--chart-enforcement)", name: "Enrolled" }]}
          />
          <MetricChart
            data={rows}
            title="Safety, Quality & Belief"
            sublabel="Signal convergence over time"
            lines={[
              { key: "safety",      color: "var(--danger)",   name: "Safety Signal" },
              { key: "dataQuality", color: "var(--success)",  name: "Data Quality"  },
              { key: "belief",      color: "var(--warning)",  name: "Mean Belief"   },
            ]}
          />
        </div>
      ) : (
        <div className="grid grid-cols-2 gap-3">
          {[0,1,2,3].map((i) => (
            <div key={i} className="card-warm animate-shimmer rounded-2xl" style={{ height: 240 }} />
          ))}
        </div>
      )}

      {result.swarm_metadata && <SwarmPanel meta={result.swarm_metadata} />}
      <ProvenanceStrip result={result} />
    </div>
  );
}
