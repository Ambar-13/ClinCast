"use client";

import { useState, useEffect } from "react";
import { ArrowRight, Brain, KeyRound, Play } from "lucide-react";
import { AppShell } from "@/components/layout/AppShell";
import { TrialConfigPanel } from "@/components/simulation/TrialConfigPanel";
import { TrialResultsPanel } from "@/components/simulation/TrialResultsPanel";
import { ProtocolUpload } from "@/components/simulation/ProtocolUpload";
import { AgentNetworkIdle } from "@/components/ui/AgentNetworkIdle";
import { ScrambleText } from "@/components/ui/ScrambleText";
import { simulate, SimulateRequest, SimulateResponse } from "@/lib/api";

const DEFAULT: SimulateRequest = {
  therapeutic_area:      "cns",
  n_patients:            400,
  n_sites:               20,
  n_rounds:              18,
  visits_per_month:      2,
  visit_duration_hours:  1.5,
  invasive_procedures:   "blood",
  ediary_frequency:      "none",
  monitoring_active:     true,
  patient_support_program: false,
  randomization_ratio:   "1:1",
  blinded:               true,
  competitive_pressure:  "none",
  enrollment_rate_modifier: 1.0,
  seed:                  0,
};

export default function SimulatePage() {
  const [req,       setReq]       = useState<SimulateRequest>(DEFAULT);
  const [useSwarm,  setUseSwarm]  = useState(() =>
    typeof window !== "undefined" ? localStorage.getItem("clincast_swarm") !== "false" : true
  );
  const [nAgents,   setNAgents]   = useState(() =>
    typeof window !== "undefined" ? +(localStorage.getItem("clincast_nagents") ?? 1000) : 1000
  );
  const [apiKey,    setApiKey]    = useState(() =>
    typeof window !== "undefined" ? (localStorage.getItem("clincast_openai_key") ?? "") : ""
  );

  useEffect(() => { localStorage.setItem("clincast_openai_key", apiKey); }, [apiKey]);
  useEffect(() => { localStorage.setItem("clincast_swarm",      String(useSwarm)); }, [useSwarm]);
  useEffect(() => { localStorage.setItem("clincast_nagents",    String(nAgents)); }, [nAgents]);
  const [result,    setResult]    = useState<SimulateResponse | null>(null);
  const [loading,   setLoading]   = useState(false);
  const [error,     setError]     = useState<string | null>(null);

  async function run() {
    setLoading(true);
    setError(null);
    try {
      setResult(await simulate({
        ...req,
        use_swarm:      useSwarm,
        n_swarm_agents: nAgents,
        openai_api_key: apiKey.trim() || undefined,
      }));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <AppShell>
      <div className="mx-auto max-w-[1560px] px-4 py-6 lg:px-8">
        <div className="mb-6">
          <h1 className="text-3xl font-bold" style={{ color: "var(--ink-900)", letterSpacing: "-0.03em" }}>
            <ScrambleText text="Trial Simulator" duration={800} delay={60} />
          </h1>
          <p className="mt-1.5 text-sm" style={{ color: "var(--ink-400)" }}>
            Agent-based clinical trial simulation with empirically-calibrated dropout, adherence, and safety dynamics.
          </p>
        </div>

        <div className="flex flex-col gap-5 lg:flex-row lg:items-start">
          {/* Left panel */}
          <aside className="w-full space-y-4 lg:w-[380px] lg:flex-shrink-0">

            {/* Protocol upload */}
            <ProtocolUpload
              openaiApiKey={apiKey || undefined}
              onApply={(params) => setReq((prev) => ({ ...prev, ...params }))}
            />

            <TrialConfigPanel value={req} onChange={setReq} />

            {/* Swarm toggle */}
            <div className="card-warm overflow-hidden">
              <div className="px-4 py-3">
                <label className="flex cursor-pointer items-start gap-3">
                  <div className="relative mt-0.5 flex-shrink-0">
                    <input type="checkbox" checked={useSwarm}
                      onChange={(e) => setUseSwarm(e.target.checked)} className="peer sr-only" />
                    <div className="h-4 w-8 rounded-full transition-colors"
                      style={{ background: useSwarm ? "#d97706" : "var(--cream-400)" }} />
                    <div className="absolute top-0.5 h-3 w-3 rounded-full bg-white shadow transition-transform"
                      style={{ left: "2px", transform: useSwarm ? "translateX(16px)" : "translateX(0)" }} />
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-1.5">
                      <Brain size={12} style={{ color: "var(--crimson-700)", flexShrink: 0 }} />
                      <p className="text-sm font-medium" style={{ color: "var(--ink-700)" }}>
                        Swarm elicitation
                      </p>
                      <span className="rounded-full px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-widest"
                        style={{ background: "rgba(245,158,11,0.12)", color: "#b45309", border: "1px solid rgba(245,158,11,0.25)" }}>
                        SWARM-ELICITED
                      </span>
                    </div>
                    <p className="mt-0.5 text-xs leading-4" style={{ color: "var(--ink-400)" }}>
                      Patient persona agents vote on belief & adherence priors before simulation.
                    </p>
                  </div>
                </label>
              </div>

              {useSwarm && (
                <div className="border-t px-4 pb-3 pt-3 space-y-3"
                  style={{ borderColor: "var(--border-warm)", background: "var(--cream-200)" }}>
                  <div>
                    <label className="block text-xs font-medium mb-1" style={{ color: "var(--ink-700)" }}>
                      Agents <span className="font-mono" style={{ color: "var(--crimson-700)" }}>{nAgents.toLocaleString()}</span>
                    </label>
                    <input type="range" min={10} max={5000} step={10}
                      value={nAgents} onChange={(e) => setNAgents(Number(e.target.value))}
                      className="w-full accent-[var(--crimson-700)] h-1.5 cursor-pointer" />
                    <div className="flex justify-between text-[10px] mt-0.5" style={{ color: "var(--ink-300)" }}>
                      <span>10 agents</span><span>5,000 agents</span>
                    </div>
                  </div>
                  <label className="block">
                    <div className="mb-1 flex items-center gap-1.5">
                      <KeyRound size={11} style={{ color: "var(--ink-400)" }} />
                      <span className="text-xs font-medium" style={{ color: "var(--ink-700)" }}>
                        OpenAI key <span style={{ color: "var(--ink-400)", fontWeight: 400 }}>(also used for protocol parsing)</span>
                      </span>
                    </div>
                    <input type="password" value={apiKey} onChange={(e) => setApiKey(e.target.value)}
                      placeholder="sk-… or leave blank to use env var"
                      className="input-warm w-full font-mono text-xs"
                      autoComplete="off" spellCheck={false} />
                  </label>
                </div>
              )}
            </div>

            <button onClick={run} disabled={loading} className="btn-primary w-full py-3 text-base">
              {loading ? (
                <>
                  <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24" fill="none">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                  </svg>
                  {useSwarm ? "Running swarm + simulation…" : "Running simulation…"}
                </>
              ) : (
                <>Run simulation <ArrowRight size={16} /></>
              )}
            </button>

            {error && (
              <div className="rounded-xl border px-3 py-2.5 text-sm"
                style={{ color: "var(--danger)", borderColor: "rgba(220,38,38,0.2)", background: "#fef2f2" }}>
                {error}
              </div>
            )}
          </aside>

          {/* Right panel */}
          <section className="min-w-0 flex-1">
            {result ? (
              <TrialResultsPanel result={result} />
            ) : (
              <div className="card-warm flex min-h-[520px] flex-col items-center justify-center gap-5 p-8 text-center"
                style={{ animation: "slideUpFade 400ms ease both" }}>
                <div style={{ animation: "floatSlow 5s ease-in-out infinite" }}>
                  <AgentNetworkIdle />
                </div>
                <div className="space-y-2">
                  <h3 className="text-2xl font-bold" style={{ color: "var(--ink-900)", letterSpacing: "-0.03em" }}>
                    Ready to simulate
                  </h3>
                  <p className="mx-auto max-w-xs text-sm leading-6" style={{ color: "var(--ink-400)" }}>
                    Configure a trial on the left — or upload a protocol document to auto-fill — then run the simulation.
                  </p>
                </div>
                <div className="flex flex-wrap justify-center gap-3">
                  {[
                    ["Area",    req.therapeutic_area.toUpperCase()],
                    ["Patients", String(req.n_patients ?? "—")],
                    ["Months",  String(req.n_rounds ?? "—")],
                    ["Visits",  req.visits_per_month != null ? `${req.visits_per_month}/mo` : "—"],
                  ].map(([label, value]) => (
                    <div key={label} className="rounded-xl border px-4 py-2.5 text-center"
                      style={{ background: "var(--cream-200)", borderColor: "var(--border-warm)" }}>
                      <p className="kicker text-[10px]">{label}</p>
                      <p className="metric-num mt-1 text-base font-bold" style={{ color: "var(--ink-900)" }}>{value}</p>
                    </div>
                  ))}
                </div>
                <p className="flex items-center gap-1.5 text-xs" style={{ color: "var(--ink-300)" }}>
                  <Play size={11} style={{ color: "var(--crimson-700)" }} />
                  <span>Click <strong style={{ color: "var(--ink-500)" }}>Run simulation</strong> to begin</span>
                </p>
              </div>
            )}
          </section>
        </div>
      </div>
    </AppShell>
  );
}
