"use client";

import { useEffect, useMemo, useState } from "react";
import dynamic from "next/dynamic";
import { AGButton, AGChip, AGLogo, AGSectionLabel, AGSurface } from "@/components/design-system";
import { AIOrb } from "@/components/Waveform";
import { getApiBaseUrl } from "@/lib/api";
import { playAudioUrl, prefetchAudio } from "@/lib/audio";

const MonacoEditor = dynamic(() => import("@monaco-editor/react").then((m) => m.default), { ssr: false });

type StageKey = "understanding" | "planning" | "implementation" | "validation" | "reflection";
type Stage = { key: StageKey; label: string; interviewer: string; candidate_task: string };
type TestDetail = { name: string; status: "pass" | "fail"; visibility?: "public" | "hidden" };
type TestResult = {
  passed: number; failed: number; total: number;
  public_passed?: number; public_total?: number;
  hidden_passed?: number; hidden_total?: number;
  details: TestDetail[]; stdout: string; stderr: string; runtime_ms: number; timed_out: boolean;
};
type Twist = { id: string; title: string; body: string; interviewer_prompt: string };
type SimReport = {
  title: string; summary: string; overall_score: number;
  breakdown: Record<string, number>; hiring_signal: string; hiring_label: string;
  overclaim_detected: boolean; twist_was_injected: boolean;
  what_proved: string[]; what_not_proved: string[]; key_quotes: string[];
  event_timeline: Array<{ ts: string; text: string }>; test_result: TestResult;
};
type GateStatus = {
  issues_by_stage: Record<StageKey, string[]>; current_issues: string[];
  can_advance: boolean; can_run_tests: boolean; can_finalize: boolean;
  code_changed: boolean; evidence_label: string;
};
type SimState = {
  session_id: string;
  scenario: { title: string; role_signal: string; objective: string; constraints: string[]; incident: string; twist?: Twist };
  stages: Stage[]; stage_requirements: Record<StageKey, string>;
  current_stage: StageKey; interviewer_message: string;
  starter_code: string; code: string; notes: Record<StageKey, string>;
  baseline_result: TestResult | null; test_result: TestResult | null;
  test_runs: TestResult[]; telemetry: Array<{ at: number; event: string; detail: string }>;
  report: SimReport | null; complete: boolean;
  twist: Twist | null; twist_injected: boolean; gate_status: GateStatus;
};

const STAGE_KEYS: StageKey[] = ["understanding", "planning", "implementation", "validation", "reflection"];
const emptyNotes: Record<StageKey, string> = { understanding: "", planning: "", implementation: "", validation: "", reflection: "" };

async function apiPost<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${getApiBaseUrl()}${path}`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  const payload = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(payload?.detail || `Request failed (${res.status})`);
  return payload as T;
}

function statusPalette(status: "pass" | "fail") {
  return status === "pass"
    ? "border-[oklch(0.76_0.16_155_/_0.28)] bg-[oklch(0.76_0.16_155_/_0.08)] text-[var(--ag-green)]"
    : "border-[oklch(0.66_0.21_24_/_0.28)] bg-[oklch(0.66_0.21_24_/_0.08)] text-[var(--ag-red)]";
}

function metricLabel(key: string) {
  return key.split("_").map((p) => p.charAt(0).toUpperCase() + p.slice(1)).join(" ");
}

function formatEventTime(at: number) {
  const d = new Date(at * 1000);
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}:${String(d.getSeconds()).padStart(2, "0")}`;
}

function hiringPalette(signal: string) {
  if (signal === "strong_hire") return "border-[oklch(0.76_0.16_155_/_0.35)] bg-[oklch(0.76_0.16_155_/_0.12)] text-[var(--ag-green)]";
  if (signal === "hire_with_followup") return "border-[oklch(0.8_0.15_200_/_0.3)] bg-[oklch(0.8_0.15_200_/_0.08)] text-[oklch(0.75_0.15_200)]";
  if (signal === "no_hire" || signal === "weak") return "border-[oklch(0.66_0.21_24_/_0.3)] bg-[oklch(0.66_0.21_24_/_0.08)] text-[var(--ag-red)]";
  return "border-[var(--ag-border)] bg-[var(--ag-surface-0)] text-[var(--ag-text-2)]";
}

const AG_DARK_THEME = {
  base: "vs-dark" as const, inherit: true,
  rules: [
    { token: "keyword", foreground: "7c9ef5" },
    { token: "string", foreground: "98c87a" },
    { token: "comment", foreground: "4a5068", fontStyle: "italic" },
    { token: "number", foreground: "e5a663" },
  ],
  colors: {
    "editor.background": "#090b12", "editor.foreground": "#b8bdd4",
    "editor.lineHighlightBackground": "#ffffff07", "editor.selectionBackground": "#3c82f630",
    "editorLineNumber.foreground": "#2e3349", "editorLineNumber.activeForeground": "#555e7a",
    "editorIndentGuide.background1": "#1e2236", "editorCursor.foreground": "#7c9ef5",
    "editor.wordHighlightBackground": "#3c82f618",
  },
};

const EDITOR_OPTIONS = {
  fontSize: 13, lineHeight: 24, minimap: { enabled: false },
  scrollBeyondLastLine: false, wordWrap: "off" as const,
  fontFamily: "'JetBrains Mono', 'Cascadia Code', 'Fira Code', 'Menlo', monospace",
  fontLigatures: true, renderLineHighlight: "line" as const,
  padding: { top: 20, bottom: 20 },
  scrollbar: { verticalScrollbarSize: 6, horizontalScrollbarSize: 6 },
  overviewRulerLanes: 0, hideCursorInOverviewRuler: true,
  contextmenu: false, tabSize: 2, insertSpaces: true, detectIndentation: false,
};

export default function InventorySimulationPage() {
  const [sim, setSim] = useState<SimState | null>(null);
  const [notes, setNotes] = useState<Record<StageKey, string>>(emptyNotes);
  const [code, setCode] = useState("");
  const [loading, setLoading] = useState(false);
  const [running, setRunning] = useState(false);
  const [speaking, setSpeaking] = useState(false);
  const [showStdout, setShowStdout] = useState(false);
  const [error, setError] = useState("");

  const stageIndex = sim ? Math.max(0, STAGE_KEYS.indexOf(sim.current_stage)) : 0;
  const stage = sim?.stages.find((s) => s.key === sim.current_stage) ?? null;
  const testResult = sim?.test_result ?? null;
  const report = sim?.report ?? null;
  const gateStatus = sim?.gate_status ?? null;
  const assessmentNotes = gateStatus?.current_issues ?? [];
  const currentNoteWords = useMemo(
    () => (notes[sim?.current_stage ?? "understanding"] ?? "").trim().split(/\s+/).filter(Boolean).length,
    [notes, sim?.current_stage],
  );
  const codeChanged = useMemo(() => {
    if (!sim) return false;
    return code.replace(/\s+/g, "") !== sim.starter_code.replace(/\s+/g, "");
  }, [code, sim]);
  const canMoveNext = Boolean(sim && stageIndex < STAGE_KEYS.length - 1 && sim.current_stage !== "implementation");
  const canRunTests = Boolean(
    sim && ["implementation", "validation"].includes(sim.current_stage) && codeChanged
    && (notes.implementation || "").trim().split(/\s+/).filter(Boolean).length >= 12
    && (gateStatus?.issues_by_stage.understanding?.length ?? 0) === 0
    && (gateStatus?.issues_by_stage.planning?.length ?? 0) === 0,
  );
  const canFinalize = Boolean(sim && sim.current_stage === "reflection" && sim.test_result && codeChanged);
  const orbState = running ? "thinking" : testResult?.failed ? "thinking" : testResult?.passed === testResult?.total ? "speaking" : "idle";

  useEffect(() => {
    const handler = (e: Event) => {
      const nextCode = (e as CustomEvent<string>).detail;
      if (typeof nextCode === "string") setCode(nextCode);
    };
    window.addEventListener("antigravity:set-simulation-code", handler);
    return () => window.removeEventListener("antigravity:set-simulation-code", handler);
  }, []);

  async function startSimulation() {
    setLoading(true); setError("");
    try {
      const started = await apiPost<SimState>("/simulation/inventory/start", {});
      setSim(started); setNotes(started.notes ?? emptyNotes); setCode(started.code);
    } catch (e) { setError(String(e)); } finally { setLoading(false); }
  }

  async function moveStage(nextStage: StageKey) {
    if (!sim) return;
    setError("");
    try {
      const updated = await apiPost<SimState>("/simulation/inventory/interviewer_turn", {
        session_id: sim.session_id, stage_key: nextStage, code, notes,
      });
      setSim(updated); setNotes(updated.notes ?? notes); setCode(updated.code);
    } catch (e) { setError(String(e)); }
  }

  async function speakInterviewer() {
    if (!sim?.interviewer_message) return;
    setSpeaking(true);
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 12_000);
    try {
      const url = await prefetchAudio(sim.interviewer_message, sim.session_id);
      await playAudioUrl(url, sim.interviewer_message, controller.signal);
    } catch (e) {
      setError(`Audio unavailable: ${String(e).replace(/^Error:\s*/, "")}`);
    } finally { window.clearTimeout(timeout); setSpeaking(false); }
  }

  async function runTests() {
    if (!sim) return;
    setRunning(true); setError("");
    try {
      const updated = await apiPost<SimState>("/simulation/inventory/run_tests", {
        session_id: sim.session_id, code, notes,
      });
      setSim(updated); setNotes(updated.notes ?? notes); setCode(updated.code);
    } catch (e) { setError(String(e)); } finally { setRunning(false); }
  }

  async function finalize() {
    if (!sim) return;
    setRunning(true); setError("");
    try {
      const updated = await apiPost<SimState>("/simulation/inventory/finalize", {
        session_id: sim.session_id, code, notes,
      });
      setSim(updated); setNotes(updated.notes ?? notes); setCode(updated.code);
    } catch (e) { setError(String(e)); } finally { setRunning(false); }
  }

  return (
    <main className="ag-shell min-h-screen px-4 py-5 text-[var(--ag-text-0)] md:px-6">
      <div className="relative z-10 mx-auto flex w-full max-w-[1680px] flex-col gap-4">

        <header className="flex flex-wrap items-center justify-between gap-4">
          <AGLogo />
          <div className="flex flex-wrap items-center gap-2">
            <AGChip active>Inventory Race Simulation</AGChip>
            <AGChip>10 Runtime Checks</AGChip>
            <AGChip>Concurrency Suite</AGChip>
            {sim?.complete && sim.report && (
              <a
                href={`/simulation/report/${sim.session_id}`}
                target="_blank"
                rel="noopener noreferrer"
                className="rounded-xl border border-[var(--ag-border)] px-3 py-2 text-sm text-[var(--ag-text-1)] transition hover:border-[var(--ag-border-strong)]"
              >
                📎 Share Report
              </a>
            )}
            <AGButton variant="secondary" href="/simulation">Payment Simulation</AGButton>
            <AGButton variant="secondary" href="/simulation/admin">Admin</AGButton>
          </div>
        </header>

        {!sim ? (

          /* ── Landing ── */
          <section className="grid min-h-[calc(100vh-6.5rem)] gap-5 lg:grid-cols-[0.95fr_1.05fr]">
            <div className="flex flex-col justify-center gap-5">
              <div className="space-y-4">
                <AGSectionLabel>Simulation V1 · Domain 2</AGSectionLabel>
                <h1 className="max-w-3xl text-5xl font-semibold leading-[1.02] tracking-[-0.055em] md:text-7xl">
                  Inventory atomicity, tested under concurrent flash-sale pressure.
                </h1>
                <p className="max-w-2xl text-base leading-8 text-[var(--ag-text-2)]">
                  A backend engineering case where the candidate traces a write-skew race, chooses a
                  locking strategy, patches the handler, survives concurrent load tests, and defends the
                  production tradeoffs.
                </p>
              </div>
              <div className="flex flex-wrap gap-3">
                <AGButton onClick={startSimulation} disabled={loading}>
                  {loading ? "Starting..." : "Start Simulation"}
                </AGButton>
                <AGButton variant="secondary" href="/simulation">Payment Retry Simulation</AGButton>
              </div>
              {error && <p className="text-sm text-[var(--ag-red)]">{error}</p>}
            </div>
            <AGSurface className="flex min-h-[520px] items-center justify-center px-6 py-6">
              <div className="relative flex w-full max-w-xl flex-col items-center gap-6 text-center">
                <AIOrb state="speaking" />
                <div>
                  <AGSectionLabel>Interviewer Presence</AGSectionLabel>
                  <p className="mt-3 text-xl leading-8 text-[var(--ag-text-1)]">
                    "Tell me where the race window opens. Tell me what invariant breaks when two requests
                    both see available&nbsp;&gt;&nbsp;0. Then show me the patch that makes that impossible."
                  </p>
                </div>
              </div>
            </AGSurface>
          </section>

        ) : (

          /* ── Interview Theater ── */
          <section className="flex min-h-[calc(100vh-6rem)] overflow-hidden rounded-2xl border border-[var(--ag-border)]">

            {/* ── Interview Channel (left) ─────────────────────────── */}
            <div className="flex w-[360px] shrink-0 flex-col border-r border-[var(--ag-border)] bg-[var(--ag-surface-0)]">

              {/* Interviewer presence */}
              <div className="border-b border-[var(--ag-border)] px-5 py-5">
                <div className="flex items-start gap-3">
                  <AIOrb state={orbState} />
                  <div className="min-w-0 flex-1">
                    <p className="font-mono text-[10px] uppercase tracking-[0.15em] text-[var(--ag-text-3)]">
                      Assessment Lead · {stage?.label ?? sim.current_stage}
                    </p>
                    <p className="mt-2 text-sm leading-6 text-[var(--ag-text-0)]">{sim.interviewer_message}</p>
                  </div>
                </div>
                {stage && (
                  <p className="mt-3 text-xs leading-5 text-[var(--ag-text-2)]">{stage.candidate_task}</p>
                )}
              </div>

              {/* Stage rail — compact pills */}
              <div className="flex items-center gap-1 border-b border-[var(--ag-border)] px-5 py-3">
                {sim.stages.map((item, index) => {
                  const active = item.key === sim.current_stage;
                  const done = index < stageIndex;
                  const locked = index > stageIndex;
                  const stageIssues = gateStatus?.issues_by_stage[item.key as StageKey] ?? [];
                  const gatePass = done && !stageIssues.length;
                  return (
                    <button
                      key={item.key}
                      disabled={locked}
                      onClick={() => moveStage(item.key)}
                      title={`${item.label}${stageIssues.length ? ": " + stageIssues.join(" ") : ""}`}
                      className={`flex h-8 flex-1 items-center justify-center rounded-lg border text-[10px] font-mono transition ${
                        active
                          ? "border-[var(--ag-border-strong)] bg-[var(--ag-blue-soft)] text-[var(--ag-text-0)]"
                          : gatePass
                            ? "border-[oklch(0.76_0.16_155_/_0.25)] bg-[oklch(0.76_0.16_155_/_0.06)] text-[var(--ag-green)]"
                            : done
                              ? "border-[oklch(0.85_0.17_85_/_0.25)] bg-[oklch(0.85_0.17_85_/_0.05)] text-[oklch(0.85_0.17_85)]"
                              : "cursor-not-allowed border-[var(--ag-border)] text-[var(--ag-text-3)] opacity-40"
                      }`}
                    >
                      {gatePass ? "✓" : `0${index + 1}`}
                    </button>
                  );
                })}
              </div>

              {/* Required artifact + gate */}
              <div className="border-b border-[var(--ag-border)] px-5 py-4">
                <p className="font-mono text-[10px] uppercase tracking-[0.15em] text-[var(--ag-text-3)]">Required Artifact</p>
                <p className="mt-2 text-xs leading-5 text-[var(--ag-text-2)]">{sim.stage_requirements?.[sim.current_stage]}</p>
                {assessmentNotes.length > 0 ? (
                  <div className="mt-2 space-y-1">
                    {assessmentNotes.map((issue) => (
                      <p key={issue} className="text-xs leading-5 text-[var(--ag-amber)]">↳ {issue}</p>
                    ))}
                  </div>
                ) : (
                  <p className="mt-2 text-xs text-[var(--ag-green)]">Gate satisfied ✓</p>
                )}
              </div>

              {/* Worklog — flex-grows to fill channel */}
              <div className="flex flex-1 flex-col px-5 py-5">
                <div className="flex items-center justify-between">
                  <p className="font-mono text-[10px] uppercase tracking-[0.15em] text-[var(--ag-text-3)]">Candidate Worklog</p>
                  <div className="flex gap-3 font-mono text-[10px] text-[var(--ag-text-3)]">
                    <span>runs.{sim.test_runs.length}</span>
                    <span>{currentNoteWords}w</span>
                  </div>
                </div>
                <textarea
                  aria-label={`${stage?.label ?? "Candidate"} worklog`}
                  value={notes[sim.current_stage] ?? ""}
                  onChange={(e) => setNotes((n) => ({ ...n, [sim.current_stage]: e.target.value }))}
                  placeholder="Think out loud — reasoning here is scored alongside your code."
                  className="mt-3 flex-1 resize-none bg-transparent text-sm leading-7 text-[var(--ag-text-0)] outline-none placeholder:text-[var(--ag-text-3)] focus:outline-none"
                />
                {report?.overclaim_detected && (
                  <p className="mt-2 text-xs text-[oklch(0.75_0.18_40)]">⚠ Overclaiming detected in candidate notes.</p>
                )}
              </div>

              {/* Telemetry — compact strip */}
              {sim.telemetry.length > 0 && (
                <div className="ag-scrollbar max-h-[120px] overflow-y-auto border-t border-[var(--ag-border)] px-5 py-3">
                  {sim.telemetry.slice(-4).map((event) => (
                    <div key={`${event.at}-${event.event}`} className="flex gap-2 py-0.5">
                      <span className="shrink-0 font-mono text-[9px] text-[var(--ag-text-3)]">{formatEventTime(event.at)}</span>
                      <span className="text-[10px] leading-4 text-[var(--ag-text-3)]">{event.detail}</span>
                    </div>
                  ))}
                </div>
              )}

              {/* Nav */}
              <div className="flex items-center gap-2 border-t border-[var(--ag-border)] px-5 py-4">
                <AGButton
                  variant="secondary"
                  disabled={stageIndex === 0}
                  onClick={() => moveStage(STAGE_KEYS[Math.max(0, stageIndex - 1)])}
                >
                  Back
                </AGButton>
                {!sim.complete && (
                  <AGButton
                    disabled={!canMoveNext}
                    onClick={() => moveStage(STAGE_KEYS[Math.min(STAGE_KEYS.length - 1, stageIndex + 1)])}
                  >
                    Next Stage
                  </AGButton>
                )}
                {error && <p className="ml-1 truncate text-xs text-[var(--ag-red)]">{error}</p>}
              </div>
            </div>

            {/* ── Technical Workspace (right) ──────────────────────── */}
            <div className="flex min-h-0 flex-1 flex-col overflow-hidden">

              {/* Workspace header */}
              <div className="flex items-center gap-3 border-b border-[var(--ag-border)] px-6 py-3">
                <h1 className="truncate text-sm font-semibold tracking-[-0.02em]">{sim.scenario.title}</h1>
                <span className="shrink-0 rounded-full border border-[var(--ag-border)] px-2.5 py-0.5 font-mono text-[10px] uppercase tracking-[0.12em] text-[var(--ag-text-3)]">
                  {gateStatus?.evidence_label ?? "Evidence incomplete"}
                </span>
                {sim.twist_injected && (
                  <span className="shrink-0 rounded-md border border-[oklch(0.75_0.18_40_/_0.3)] bg-[oklch(0.75_0.18_40_/_0.07)] px-2 py-0.5 font-mono text-[10px] text-[oklch(0.75_0.18_40)]">
                    Production twist active
                  </span>
                )}
                <div className="ml-auto flex shrink-0 items-center gap-2">
                  {testResult?.stdout && (
                    <AGButton variant="secondary" onClick={() => setShowStdout((v) => !v)}>
                      {showStdout ? "Hide Output" : "Show Output"}
                    </AGButton>
                  )}
                  <AGButton variant="secondary" disabled={running || !canRunTests} onClick={runTests}>
                    {running ? "Running..." : "Run Tests"}
                  </AGButton>
                  <AGButton disabled={running || !canFinalize} onClick={finalize}>
                    Finalize
                  </AGButton>
                </div>
              </div>

              {/* Stage-adaptive content */}
              {sim.complete && report ? (

                /* ── COMPLETE: Inline report ── */
                <div className="ag-scrollbar flex-1 overflow-y-auto px-8 py-8">
                  <div className="max-w-2xl space-y-6">
                    <div>
                      <p className="font-mono text-[10px] uppercase tracking-[0.15em] text-[var(--ag-text-3)]">Final Report</p>
                    </div>
                    <div className="flex items-end gap-4">
                      <p className="font-mono text-7xl font-semibold tracking-[-0.07em]">{report.overall_score}</p>
                      <div className="pb-2">
                        <div className={`inline-block rounded-lg border px-3 py-1.5 text-xs font-semibold tracking-wide ${hiringPalette(report.hiring_signal)}`}>
                          {report.hiring_label ?? report.hiring_signal}
                        </div>
                        <p className="mt-1 text-xs text-[var(--ag-text-3)]">final score · Assessment Report</p>
                      </div>
                    </div>
                    <p className="text-sm leading-7 text-[var(--ag-text-2)]">{report.summary}</p>
                    <div className="space-y-3">
                      {Object.entries(report.breakdown).map(([key, value]) => (
                        <div key={key}>
                          <div className="flex justify-between text-xs text-[var(--ag-text-2)]">
                            <span>{metricLabel(key)}</span>
                            <span>{value}</span>
                          </div>
                          <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-[var(--ag-surface-2)]">
                            <div className="h-full rounded-full bg-[var(--ag-blue)]" style={{ width: `${value}%` }} />
                          </div>
                        </div>
                      ))}
                    </div>
                    {report.what_proved?.length > 0 && (
                      <div>
                        <p className="font-mono text-[10px] uppercase tracking-[0.14em] text-[var(--ag-green)]">What Was Proved</p>
                        <ul className="mt-2 space-y-1.5">
                          {report.what_proved.map((item) => (
                            <li key={item} className="flex gap-2 text-xs leading-5 text-[var(--ag-text-2)]">
                              <span className="mt-0.5 text-[var(--ag-green)]">✓</span>{item}
                            </li>
                          ))}
                        </ul>
                      </div>
                    )}
                    {report.what_not_proved?.length > 0 && (
                      <div>
                        <p className="font-mono text-[10px] uppercase tracking-[0.14em] text-[var(--ag-red)]">What Remains Unproven</p>
                        <ul className="mt-2 space-y-1.5">
                          {report.what_not_proved.map((item) => (
                            <li key={item} className="flex gap-2 text-xs leading-5 text-[var(--ag-text-2)]">
                              <span className="mt-0.5 text-[var(--ag-red)]">○</span>{item}
                            </li>
                          ))}
                        </ul>
                      </div>
                    )}
                    {report.key_quotes?.length > 0 && (
                      <div>
                        <p className="font-mono text-[10px] uppercase tracking-[0.14em] text-[var(--ag-text-3)]">Candidate Quotes</p>
                        <div className="mt-2 space-y-2">
                          {report.key_quotes.map((quote) => (
                            <blockquote key={quote} className="border-l-2 border-[var(--ag-border-strong)] pl-3 text-xs italic leading-5 text-[var(--ag-text-2)]">
                              {quote}
                            </blockquote>
                          ))}
                        </div>
                      </div>
                    )}
                    {report.event_timeline?.length > 0 && (
                      <div>
                        <p className="font-mono text-[10px] uppercase tracking-[0.14em] text-[var(--ag-text-3)]">Session Timeline</p>
                        <div className="mt-2 space-y-2">
                          {report.event_timeline.map((entry, i) => (
                            <div key={i} className="flex gap-3 border-l border-[var(--ag-border)] pl-3">
                              <span className="shrink-0 font-mono text-[10px] text-[var(--ag-text-3)]">{entry.ts}</span>
                              <span className="text-xs leading-5 text-[var(--ag-text-2)]">{entry.text}</span>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                    {report.twist_was_injected && (
                      <p className="text-[10px] text-[oklch(0.75_0.18_40)]">↳ Production twist was injected during this session.</p>
                    )}
                  </div>
                </div>

              ) : sim.current_stage === "understanding" ? (

                /* ── UNDERSTANDING: Case brief reading view ── */
                <div className="ag-scrollbar flex-1 overflow-y-auto px-8 py-8">
                  <div className="max-w-2xl space-y-6">
                    <div>
                      <p className="font-mono text-[10px] uppercase tracking-[0.15em] text-[var(--ag-text-3)]">Incident Brief</p>
                      <p className="mt-3 whitespace-pre-line text-base leading-8 text-[var(--ag-text-0)]">{sim.scenario.incident}</p>
                    </div>
                    <div className="rounded-xl border border-[var(--ag-border)] bg-[var(--ag-surface-0)] px-4 py-4">
                      <p className="font-mono text-[10px] uppercase text-[var(--ag-text-3)]">Role Signal</p>
                      <p className="mt-2 text-sm leading-6 text-[var(--ag-text-1)]">{sim.scenario.role_signal}</p>
                    </div>
                    <div>
                      <p className="font-mono text-[10px] uppercase text-[var(--ag-text-3)]">Constraints</p>
                      <div className="mt-3 space-y-2">
                        {sim.scenario.constraints.map((c) => (
                          <div key={c} className="flex gap-3 text-sm leading-6 text-[var(--ag-text-2)]">
                            <span className="mt-0.5 shrink-0 text-[var(--ag-text-3)]">→</span>
                            <span>{c}</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  </div>
                </div>

              ) : sim.current_stage === "planning" ? (

                /* ── PLANNING: Constraints reference + code ── */
                <div className="flex min-h-0 flex-1">
                  <div className="ag-scrollbar w-[300px] shrink-0 overflow-y-auto border-r border-[var(--ag-border)] px-6 py-6">
                    <p className="font-mono text-[10px] uppercase tracking-[0.15em] text-[var(--ag-text-3)]">Constraints</p>
                    <div className="mt-4 space-y-3">
                      {sim.scenario.constraints.map((c) => (
                        <div key={c} className="rounded-xl border border-[var(--ag-border)] bg-[var(--ag-surface-0)] px-3 py-3 text-xs leading-5 text-[var(--ag-text-2)]">
                          {c}
                        </div>
                      ))}
                    </div>
                    <div className="mt-6">
                      <p className="font-mono text-[10px] uppercase tracking-[0.15em] text-[var(--ag-text-3)]">Objective</p>
                      <p className="mt-2 text-xs leading-5 text-[var(--ag-text-2)]">{sim.scenario.objective}</p>
                    </div>
                  </div>
                  <div className="flex min-h-0 flex-1 flex-col">
                    <p className="border-b border-[var(--ag-border)] px-4 py-2 font-mono text-[10px] uppercase tracking-[0.15em] text-[var(--ag-text-3)]">
                      inventory.mjs · starter reference
                    </p>
                    <div className="min-h-0 flex-1">
                      <MonacoEditor
                        height="100%"
                        language="javascript"
                        value={code}
                        onChange={(v) => setCode(v ?? "")}
                        theme="ag-dark"
                        beforeMount={(monaco) => monaco.editor.defineTheme("ag-dark", AG_DARK_THEME)}
                        options={{ ...EDITOR_OPTIONS, ariaLabel: "inventory.mjs code editor" }}
                      />
                    </div>
                  </div>
                </div>

              ) : (

                /* ── IMPLEMENTATION / VALIDATION / REFLECTION: Code-first ── */
                <div className="flex min-h-0 flex-1 flex-col">
                  <div className="flex items-center border-b border-[var(--ag-border)] px-4 py-2">
                    <p className="font-mono text-[10px] uppercase tracking-[0.15em] text-[var(--ag-text-3)]">
                      inventory.mjs · atomicity boundary
                    </p>
                  </div>
                  <div className="min-h-0 flex-1">
                    <MonacoEditor
                      height="100%"
                      language="javascript"
                      value={code}
                      onChange={(v) => setCode(v ?? "")}
                      theme="ag-dark"
                      beforeMount={(monaco) => monaco.editor.defineTheme("ag-dark", AG_DARK_THEME)}
                      options={{ ...EDITOR_OPTIONS, ariaLabel: "inventory.mjs code editor" }}
                    />
                  </div>

                  {testResult && (
                    <div className="border-t border-[var(--ag-border)]">
                      <div className="flex items-center gap-4 px-5 py-3">
                        <p className="font-mono text-xs text-[var(--ag-text-2)]">
                          {testResult.passed}/{testResult.total} checks passing
                        </p>
                        <div className="flex gap-3 text-xs text-[var(--ag-text-3)]">
                          <span>public {testResult.public_passed ?? 0}/{testResult.public_total ?? 0}</span>
                          <span>hidden {testResult.hidden_passed ?? 0}/{testResult.hidden_total ?? 0}</span>
                          <span>{testResult.runtime_ms}ms</span>
                        </div>
                      </div>
                      <div className="ag-scrollbar max-h-52 overflow-y-auto px-5 pb-4">
                        <div className="grid gap-2 sm:grid-cols-2">
                          {testResult.details.map((detail) => (
                            <div key={detail.name} className={`rounded-xl border px-3 py-2.5 ${statusPalette(detail.status)}`}>
                              <div className="flex items-start justify-between gap-2">
                                <p className="text-xs leading-5 text-[var(--ag-text-1)]">{detail.name}</p>
                                <span className="shrink-0 font-mono text-[9px] uppercase opacity-70">
                                  {detail.visibility === "hidden" ? "hidden " : ""}{detail.status}
                                </span>
                              </div>
                            </div>
                          ))}
                        </div>
                      </div>
                    </div>
                  )}

                  {showStdout && testResult?.stdout && (
                    <div className="max-h-44 overflow-y-auto border-t border-[var(--ag-border)] bg-[oklch(0.06_0.01_265)] px-5 py-4">
                      <p className="mb-2 font-mono text-[10px] uppercase tracking-[0.16em] text-[var(--ag-text-3)]">Test Runner Output</p>
                      <pre className="whitespace-pre-wrap font-mono text-[11px] leading-5 text-[var(--ag-text-2)]">{testResult.stdout}</pre>
                      {testResult.stderr && (
                        <pre className="mt-2 whitespace-pre-wrap font-mono text-[11px] leading-5 text-[var(--ag-red)]">{testResult.stderr}</pre>
                      )}
                    </div>
                  )}

                  {sim.twist_injected && sim.twist && (
                    <div className="border-t border-[oklch(0.75_0.18_40_/_0.35)] bg-[oklch(0.75_0.18_40_/_0.06)] px-5 py-4">
                      <p className="font-mono text-[10px] uppercase tracking-[0.16em] text-[oklch(0.75_0.18_40)]">{sim.twist.title}</p>
                      <p className="mt-2 whitespace-pre-line text-sm leading-7 text-[var(--ag-text-1)]">{sim.twist.body}</p>
                    </div>
                  )}
                </div>
              )}
            </div>
          </section>
        )}
      </div>
    </main>
  );
}
