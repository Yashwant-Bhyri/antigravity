"use client";

import { useEffect, useState } from "react";
import { AGButton, AGChip, AGLogo, AGSectionLabel, AGSurface } from "@/components/design-system";
import { getApiBaseUrl } from "@/lib/api";

type SessionRow = {
  session_id: string;
  scenario: string;
  complete: boolean;
  current_stage: string;
  overall_score: number | null;
  hiring_signal: string | null;
  hiring_label: string | null;
  passed: number | null;
  total: number | null;
  test_runs: number;
  twist_injected: boolean;
  created_at: number | null;
  updated_at: number | null;
};

const SIGNAL_PALETTE: Record<string, string> = {
  strong_hire: "text-[var(--ag-green)] border-[oklch(0.76_0.16_155_/_0.35)] bg-[oklch(0.76_0.16_155_/_0.1)]",
  hire_with_followup: "text-[oklch(0.75_0.15_200)] border-[oklch(0.8_0.15_200_/_0.3)] bg-[oklch(0.8_0.15_200_/_0.08)]",
  mixed: "text-[var(--ag-text-1)] border-[var(--ag-border)] bg-[var(--ag-surface-0)]",
  weak: "text-[oklch(0.75_0.18_40)] border-[oklch(0.75_0.18_40_/_0.3)] bg-[oklch(0.75_0.18_40_/_0.07)]",
  no_hire: "text-[var(--ag-red)] border-[oklch(0.66_0.21_24_/_0.3)] bg-[oklch(0.66_0.21_24_/_0.08)]",
};

function relativeTime(ts: number | null) {
  if (!ts) return "—";
  const diff = Math.round((Date.now() / 1000) - ts);
  if (diff < 60) return `${diff}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

function ScoreBadge({ score, signal }: { score: number | null; signal: string | null }) {
  if (score === null) return <span className="text-[var(--ag-text-3)]">—</span>;
  const palette = SIGNAL_PALETTE[signal ?? "mixed"] ?? SIGNAL_PALETTE.mixed;
  return (
    <span className={`inline-block rounded-lg border px-2 py-0.5 font-mono text-xs font-semibold ${palette}`}>
      {score}
    </span>
  );
}

export default function SimulationAdminPage() {
  const [sessions, setSessions] = useState<SessionRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [filter, setFilter] = useState<"all" | "complete" | "active">("all");
  const [sort, setSort] = useState<"time" | "score">("time");

  async function loadSessions() {
    setLoading(true);
    setError("");
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 8000);
    try {
      const response = await fetch(`${getApiBaseUrl()}/simulation/sessions`, { signal: controller.signal });
      const data = await response.json().catch(() => []);
      if (!response.ok) throw new Error(data?.detail || `Could not load sessions (${response.status})`);
      setSessions(Array.isArray(data) ? data : []);
    } catch (e) {
      setError(e instanceof Error && e.name === "AbortError" ? "Session index timed out. Try refresh." : String(e));
    } finally {
      window.clearTimeout(timeout);
      setLoading(false);
    }
  }

  useEffect(() => {
    loadSessions();
  }, []);

  function refresh() {
    loadSessions();
  }

  const filtered = sessions
    .filter((s) => {
      if (filter === "complete") return s.complete;
      if (filter === "active") return !s.complete;
      return true;
    })
    .sort((a, b) => {
      if (sort === "score") return (b.overall_score ?? -1) - (a.overall_score ?? -1);
      return (b.updated_at ?? 0) - (a.updated_at ?? 0);
    });

  const completed = sessions.filter((s) => s.complete).length;
  const avgScore = sessions.filter((s) => s.overall_score !== null).length
    ? Math.round(sessions.filter((s) => s.overall_score !== null).reduce((acc, s) => acc + (s.overall_score ?? 0), 0) / sessions.filter((s) => s.overall_score !== null).length)
    : null;
  const strongHires = sessions.filter((s) => s.hiring_signal === "strong_hire").length;

  return (
    <main className="ag-shell min-h-screen px-4 py-6 text-[var(--ag-text-0)] md:px-8">
      <div className="mx-auto max-w-[1400px]">
        <header className="flex flex-wrap items-center justify-between gap-4">
          <AGLogo />
          <div className="flex flex-wrap items-center gap-2">
            <AGChip active>Simulation Admin</AGChip>
            <AGButton variant="secondary" href="/simulation">New Simulation</AGButton>
          </div>
        </header>

        <div className="mt-6 grid gap-4 sm:grid-cols-4">
          {[
            { label: "Total Sessions", value: sessions.length },
            { label: "Completed", value: completed },
            { label: "Avg Score", value: avgScore !== null ? avgScore : "—" },
            { label: "Strong Hires", value: strongHires },
          ].map(({ label, value }) => (
            <AGSurface key={label} className="px-5 py-4">
              <p className="font-mono text-[10px] uppercase tracking-[0.16em] text-[var(--ag-text-3)]">{label}</p>
              <p className="mt-2 font-mono text-4xl font-semibold tracking-[-0.06em]">{value}</p>
            </AGSurface>
          ))}
        </div>

        <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
          <div className="flex gap-2">
            {(["all", "complete", "active"] as const).map((f) => (
              <button
                key={f}
                onClick={() => setFilter(f)}
                className={`rounded-xl border px-3 py-1.5 text-xs capitalize transition ${
                  filter === f
                    ? "border-[var(--ag-border-strong)] bg-[var(--ag-blue-soft)] text-[var(--ag-text-0)]"
                    : "border-[var(--ag-border)] text-[var(--ag-text-2)] hover:border-[var(--ag-border-strong)]"
                }`}
              >
                {f}
              </button>
            ))}
          </div>
          <div className="flex gap-2">
            <select
              value={sort}
              onChange={(e) => setSort(e.target.value as "time" | "score")}
              className="rounded-xl border border-[var(--ag-border)] bg-[var(--ag-surface-0)] px-3 py-1.5 text-xs text-[var(--ag-text-2)] outline-none"
            >
              <option value="time">Sort: Most Recent</option>
              <option value="score">Sort: Highest Score</option>
            </select>
            <AGButton variant="secondary" onClick={refresh} disabled={loading}>
              {loading ? "Loading…" : "Refresh"}
            </AGButton>
          </div>
        </div>

        <AGSurface className="mt-4 overflow-hidden px-0 py-0">
          {error ? (
            <div className="px-6 py-12 text-center">
              <p className="text-sm text-[var(--ag-red)]">{error}</p>
              <button onClick={refresh} className="mt-3 text-xs text-[var(--ag-blue)] hover:underline">
                Retry session index
              </button>
            </div>
          ) : loading && sessions.length === 0 ? (
            <div className="px-6 py-12 text-center text-sm text-[var(--ag-text-3)]">Loading sessions…</div>
          ) : filtered.length === 0 ? (
            <div className="px-6 py-12 text-center text-sm text-[var(--ag-text-3)]">
              No {filter !== "all" ? filter : ""} sessions found.
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-[var(--ag-border)] text-left text-[10px] font-mono uppercase tracking-[0.14em] text-[var(--ag-text-3)]">
                    {["Session", "Scenario", "Stage", "Score", "Tests", "Runs", "Twist", "Updated"].map((h) => (
                      <th key={h} className="px-4 py-3 font-normal">{h}</th>
                    ))}
                    <th className="px-4 py-3 font-normal">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {filtered.map((s, i) => (
                    <tr
                      key={s.session_id}
                      className={`border-b border-[var(--ag-border)] transition hover:bg-[var(--ag-surface-0)] ${
                        i === filtered.length - 1 ? "border-b-0" : ""
                      }`}
                    >
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-2">
                          <span className={`inline-block h-2 w-2 rounded-full ${s.complete ? "bg-[var(--ag-green)]" : "bg-[oklch(0.75_0.18_40)]"}`} />
                          <span className="font-mono text-xs text-[var(--ag-text-3)]">{s.session_id.slice(0, 8)}</span>
                        </div>
                      </td>
                      <td className="px-4 py-3 text-xs text-[var(--ag-text-2)]">{s.scenario}</td>
                      <td className="px-4 py-3">
                        <span className="font-mono text-xs text-[var(--ag-text-3)] capitalize">{s.current_stage}</span>
                      </td>
                      <td className="px-4 py-3">
                        <ScoreBadge score={s.overall_score} signal={s.hiring_signal} />
                        {s.hiring_label && (
                          <span className="ml-2 text-xs text-[var(--ag-text-3)]">{s.hiring_label}</span>
                        )}
                      </td>
                      <td className="px-4 py-3 font-mono text-xs text-[var(--ag-text-2)]">
                        {s.passed !== null ? `${s.passed}/${s.total}` : "—"}
                      </td>
                      <td className="px-4 py-3 font-mono text-xs text-[var(--ag-text-3)]">{s.test_runs}</td>
                      <td className="px-4 py-3 text-xs">
                        {s.twist_injected ? <span className="text-[oklch(0.75_0.18_40)]">✓</span> : <span className="text-[var(--ag-text-3)]">—</span>}
                      </td>
                      <td className="px-4 py-3 text-xs text-[var(--ag-text-3)]">{relativeTime(s.updated_at)}</td>
                      <td className="px-4 py-3">
                        {s.complete && (
                          <a
                            href={`/simulation/report/${s.session_id}`}
                            className="text-xs text-[var(--ag-blue)] hover:underline"
                          >
                            View Report →
                          </a>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </AGSurface>
      </div>
    </main>
  );
}
