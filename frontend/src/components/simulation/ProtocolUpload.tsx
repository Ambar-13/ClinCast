"use client";

import { useRef, useState } from "react";
import { FileText, Upload, CheckCircle, AlertCircle, X, Sparkles } from "lucide-react";
import { parseProtocol, ParsedProtocol, SimulateRequest } from "@/lib/api";

interface Props {
  onApply: (params: Partial<SimulateRequest>) => void;
  openaiApiKey?: string;
}

const FIELD_LABELS: Record<string, string> = {
  therapeutic_area:        "Therapeutic area",
  n_patients:              "Patients",
  n_sites:                 "Sites",
  n_rounds:                "Duration (months)",
  visits_per_month:        "Visits / month",
  visit_duration_hours:    "Visit duration",
  invasive_procedures:     "Invasive procedures",
  ediary_frequency:        "eDiary frequency",
  monitoring_active:       "RBM monitoring",
  patient_support_program: "Patient support",
  randomization_ratio:     "Randomization ratio",
  blinded:                 "Blinded",
  competitive_pressure:    "Competitive pressure",
  enrollment_rate_modifier:"Enrollment rate",
};

function formatValue(key: string, v: unknown): string {
  if (typeof v === "boolean") return v ? "Yes" : "No";
  if (key === "visits_per_month") return `${v}/mo`;
  if (key === "visit_duration_hours") return `${v}h`;
  if (key === "enrollment_rate_modifier") return `${v}×`;
  if (key === "n_rounds") return `${v} mo`;
  return String(v);
}

export function ProtocolUpload({ onApply, openaiApiKey }: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [file, setFile]         = useState<File | null>(null);
  const [loading, setLoading]   = useState(false);
  const [result, setResult]     = useState<ParsedProtocol | null>(null);
  const [error, setError]       = useState<string | null>(null);

  const handleFile = (f: File) => {
    setFile(f);
    setResult(null);
    setError(null);
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragging(false);
    const f = e.dataTransfer.files[0];
    if (f) handleFile(f);
  };

  const parse = async () => {
    if (!file) return;
    setLoading(true);
    setError(null);
    try {
      const parsed = await parseProtocol(file, openaiApiKey);
      setResult(parsed);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  };

  const apply = () => {
    if (result?.params) onApply(result.params);
  };

  const reset = () => {
    setFile(null);
    setResult(null);
    setError(null);
  };

  const extractedKeys = result
    ? Object.keys(FIELD_LABELS).filter((k) => result.params[k as keyof typeof result.params] !== undefined)
    : [];

  return (
    <div className="card-warm overflow-hidden">
      <div className="px-4 py-3 flex items-center justify-between"
        style={{ borderBottom: file || result ? "1px solid var(--border-warm)" : undefined }}>
        <div className="flex items-center gap-2">
          <FileText size={12} style={{ color: "var(--primary-600)" }} />
          <p className="kicker text-[10px]">Document Auto-fill</p>
          <span className="rounded-full px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-widest"
            style={{ background: "rgba(7,160,195,0.08)", color: "var(--primary-700)", border: "1px solid rgba(7,160,195,0.15)" }}>
            AI
          </span>
        </div>
        {file && (
          <button onClick={reset} className="p-0.5 rounded hover:opacity-70 transition-opacity">
            <X size={12} style={{ color: "var(--ink-400)" }} />
          </button>
        )}
      </div>

      <div className="px-4 pb-4 pt-3 space-y-3">
        {/* Drop zone */}
        {!file && !result && (
          <div
            onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
            onDragLeave={() => setDragging(false)}
            onDrop={handleDrop}
            onClick={() => inputRef.current?.click()}
            className="flex flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed py-6 cursor-pointer transition-colors"
            style={{
              borderColor: dragging ? "var(--primary-600)" : "var(--border-warm)",
              background: dragging ? "rgba(7,160,195,0.04)" : "var(--surface-100)",
            }}
          >
            <Upload size={20} style={{ color: dragging ? "var(--primary-600)" : "var(--ink-300)" }} />
            <p className="text-xs font-medium" style={{ color: "var(--ink-600)" }}>
              Drop any document
            </p>
            <p className="text-[10px]" style={{ color: "var(--ink-400)" }}>
              Protocol · Policy · Strategy · Any PDF — up to 20 MB
            </p>
            <input
              ref={inputRef}
              type="file" accept=".pdf,.md,.txt" className="hidden"
              onChange={(e) => { const f = e.target.files?.[0]; if (f) handleFile(f); }}
            />
          </div>
        )}

        {/* File selected, not yet parsed */}
        {file && !result && !loading && (
          <div className="space-y-3">
            <div className="flex items-center gap-2.5 rounded-lg border px-3 py-2"
              style={{ borderColor: "var(--border-warm)", background: "var(--surface-50)" }}>
              <FileText size={14} style={{ color: "var(--primary-600)", flexShrink: 0 }} />
              <div className="min-w-0 flex-1">
                <p className="text-xs font-medium truncate" style={{ color: "var(--ink-700)" }}>{file.name}</p>
                <p className="text-[10px]" style={{ color: "var(--ink-400)" }}>
                  {(file.size / 1024).toFixed(0)} KB
                </p>
              </div>
            </div>
            <button onClick={parse} className="btn-primary w-full py-2 text-xs gap-1.5">
              <Sparkles size={12} />
              Parse with AI
            </button>
          </div>
        )}

        {/* Loading */}
        {loading && (
          <div className="flex flex-col items-center gap-2 py-4">
            <svg className="animate-spin h-5 w-5" viewBox="0 0 24 24" fill="none">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
            </svg>
            <p className="text-xs" style={{ color: "var(--ink-500)" }}>Reading document &amp; inferring parameters…</p>
          </div>
        )}

        {/* Error */}
        {error && (
          <div className="rounded-lg border px-3 py-2 flex items-start gap-2"
            style={{ borderColor: "rgba(220,38,38,0.2)", background: "#fef2f2" }}>
            <AlertCircle size={12} style={{ color: "var(--danger)", flexShrink: 0, marginTop: 1 }} />
            <p className="text-[11px]" style={{ color: "var(--danger)" }}>{error}</p>
          </div>
        )}

        {/* Results */}
        {result && (
          <div className="space-y-3">
            {/* Document type + title */}
            <div className="flex items-start gap-2">
              <CheckCircle size={13} style={{ color: "var(--success)", flexShrink: 0, marginTop: 1 }} />
              <div className="min-w-0">
                <p className="text-xs font-semibold truncate" style={{ color: "var(--ink-800)" }}>
                  {result.title}
                </p>
                <div className="flex items-center gap-1.5 mt-0.5">
                  <span className="text-[10px] font-bold uppercase tracking-widest rounded-full px-1.5 py-0.5"
                    style={{ background: "rgba(7,160,195,0.08)", color: "var(--primary-700)", border: "1px solid rgba(7,160,195,0.15)" }}>
                    {result.document_type || "Document"}
                  </span>
                  <span className="text-[10px]" style={{ color: "var(--ink-400)" }}>
                    {result.confidence === "high" ? "High" : result.confidence === "medium" ? "Medium" : "Low"} confidence
                  </span>
                </div>
              </div>
            </div>

            {/* AI Summary */}
            {result.summary && (
              <div className="rounded-lg px-3 py-2" style={{ background: "var(--surface-100)", border: "1px solid var(--border-warm)" }}>
                <p className="text-[10px] leading-4" style={{ color: "var(--ink-600)" }}>
                  <span className="font-semibold" style={{ color: "var(--ink-700)" }}>What this is: </span>
                  {result.summary}
                </p>
              </div>
            )}

            {/* Field list */}
            <div className="rounded-lg border divide-y overflow-hidden" style={{ borderColor: "var(--border-warm)" }}>
              {extractedKeys.map((k) => {
                const src = result.field_sources?.[k] ?? (result.assumed_fields.includes(k) ? "default" : "explicit");
                const reasoning = result.field_reasoning?.[k];
                return (
                  <div key={k} className="px-3 py-1.5" style={{ background: "var(--surface-50)" }}>
                    <div className="flex items-center justify-between">
                      <span className="text-[10px]" style={{ color: "var(--ink-500)" }}>{FIELD_LABELS[k]}</span>
                      <div className="flex items-center gap-1.5">
                        {/* Source badge */}
                        <span className="text-[10px] font-medium flex items-center gap-0.5"
                          style={{ color: src === "explicit" ? "#16a34a" : src === "inferred" ? "var(--primary-700)" : "var(--ink-300)" }}>
                          <span className="inline-block w-1.5 h-1.5 rounded-full"
                            style={{ background: src === "explicit" ? "#16a34a" : src === "inferred" ? "var(--primary-600)" : "var(--ink-300)" }} />
                          {src === "explicit" ? "from doc" : src === "inferred" ? "AI inferred" : "assumed"}
                        </span>
                        <span className="text-[10px] font-semibold font-mono" style={{ color: "var(--ink-800)" }}>
                          {formatValue(k, result.params[k as keyof typeof result.params])}
                        </span>
                      </div>
                    </div>
                    {/* Reasoning line for inferred fields */}
                    {src === "inferred" && reasoning && (
                      <p className="text-[10px] mt-0.5 italic" style={{ color: "var(--ink-400)" }}>
                        {reasoning.length > 90 ? reasoning.slice(0, 87) + "…" : reasoning}
                      </p>
                    )}
                  </div>
                );
              })}
            </div>

            <button onClick={apply} className="btn-primary w-full py-2 text-xs">
              Apply to form
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
