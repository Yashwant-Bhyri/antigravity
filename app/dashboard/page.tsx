import { AGButton, AGLogo, AGMetricCard, AGSectionLabel, AGSurface, AGVerdictBadge } from "@/components/design-system";
import { getApiBaseUrl } from "@/lib/api";

type Session = {
  session_id: string;
  scores: Record<string, number>;
  weakness_summary: Record<string, number>;
  total_questions: number;
  failure_surface: Record<string, number>;
  raw_weaknesses: { severity: string }[];
};

async function getSessions(): Promise<Session[]> {
  try {
    const res = await fetch(`${getApiBaseUrl()}/sessions`, { cache: "no-store" });
    if (!res.ok) return [];
    return res.json();
  } catch {
    return [];
  }
}

function recommendationFromSurface(surface: Record<string, number>): "HIRE" | "MAYBE" | "NO HIRE" | "N/A" {
  const values = Object.values(surface ?? {});
  if (!values.length) return "N/A";
  const avg = values.reduce((sum, value) => sum + value, 0) / values.length;
  if (avg < 0.3) return "HIRE";
  if (avg < 0.6) return "MAYBE";
  return "NO HIRE";
}

export default async function DashboardPage() {
  const sessions = await getSessions();
  const hireCount = sessions.filter((session) => recommendationFromSurface(session.failure_surface) === "HIRE").length;
  const maybeCount = sessions.filter((session) => recommendationFromSurface(session.failure_surface) === "MAYBE").length;
  const noHireCount = sessions.filter((session) => recommendationFromSurface(session.failure_surface) === "NO HIRE").length;
  const avgWeaknesses =
    sessions.length > 0
      ? (sessions.reduce((sum, session) => sum + session.raw_weaknesses.length, 0) / sessions.length).toFixed(1)
      : "0.0";

  return (
    <main className="ag-shell min-h-screen px-6 py-8 md:px-10">
      <div className="mx-auto flex w-full max-w-6xl flex-col gap-8">
        <div className="flex flex-col gap-5 md:flex-row md:items-end md:justify-between">
          <div className="space-y-4">
            <AGLogo />
            <div className="space-y-3">
              <AGSectionLabel>Recruiter Dashboard</AGSectionLabel>
              <h1 className="text-3xl font-semibold tracking-[-0.04em] text-[var(--ag-text-0)] md:text-5xl">
                Every interview, one pressure ledger.
              </h1>
              <p className="max-w-3xl text-sm leading-7 text-[var(--ag-text-2)]">
                This view is where the adversarial loop becomes recruiter signal: how many questions we needed,
                where the candidate broke, and whether the failure surface still leaves enough confidence to hire.
              </p>
            </div>
          </div>

          <AGButton href="/" className="w-fit">
            + New Interview
          </AGButton>
        </div>

        <div className="grid gap-4 md:grid-cols-4">
          <AGMetricCard label="Sessions" value={sessions.length} subtext="completed or persisted runs" emphasis="blue" />
          <AGMetricCard label="Hire" value={hireCount} subtext="low average failure surface" emphasis="green" />
          <AGMetricCard label="Maybe" value={maybeCount} subtext="mixed signal under pressure" emphasis="amber" />
          <AGMetricCard label="Avg Weaknesses" value={avgWeaknesses} subtext="logged weaknesses per session" emphasis="red" />
        </div>

        <AGSurface className="overflow-hidden">
          <div className="flex items-center justify-between border-b border-[var(--ag-border)] px-6 py-5">
            <div>
              <AGSectionLabel>Recent Sessions</AGSectionLabel>
              <p className="mt-2 text-sm text-[var(--ag-text-2)]">
                {sessions.length ? `${sessions.length} interview${sessions.length === 1 ? "" : "s"} persisted` : "No sessions available yet"}
              </p>
            </div>
            <span className="font-mono text-xs uppercase tracking-[0.16em] text-[var(--ag-text-3)]">
              /sessions-backed
            </span>
          </div>

          {sessions.length === 0 ? (
            <div className="px-6 py-16 text-center">
              <p className="text-lg font-medium text-[var(--ag-text-1)]">No interviews yet.</p>
              <p className="mt-2 text-sm text-[var(--ag-text-3)]">
                Start one from the home page to populate the dashboard.
              </p>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="min-w-full">
                <thead className="bg-[var(--ag-surface-0)]">
                  <tr>
                    {["Session", "Questions", "Weaknesses", "Surface", "Verdict"].map((label) => (
                      <th
                        key={label}
                        className="px-6 py-4 text-left font-mono text-[10px] font-semibold uppercase tracking-[0.16em] text-[var(--ag-text-3)]"
                      >
                        {label}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {sessions.map((session, index) => {
                    const verdict = recommendationFromSurface(session.failure_surface);
                    const highSeverityCount = session.raw_weaknesses.filter((item) => item.severity === "high").length;
                    const averageSurface = Object.values(session.failure_surface ?? {}).length
                      ? Object.values(session.failure_surface).reduce((sum, value) => sum + value, 0) /
                        Object.values(session.failure_surface).length
                      : 0;
                    return (
                      <tr
                        key={session.session_id}
                        className={index % 2 === 0 ? "bg-transparent" : "bg-[oklch(0.12_0.014_265_/_0.45)]"}
                      >
                        <td className="px-6 py-5">
                          <a href={`/report/${session.session_id}`} className="block">
                            <span className="font-mono text-sm text-[var(--ag-text-1)]">
                              {session.session_id.slice(0, 8)}…
                            </span>
                          </a>
                        </td>
                        <td className="px-6 py-5 text-sm text-[var(--ag-text-1)]">{session.total_questions}</td>
                        <td className="px-6 py-5">
                          <div className="space-y-1">
                            <p className="text-sm text-[var(--ag-text-1)]">{session.raw_weaknesses.length} logged</p>
                            {highSeverityCount > 0 && (
                              <p className="text-xs text-[var(--ag-red)]">{highSeverityCount} high severity</p>
                            )}
                          </div>
                        </td>
                        <td className="px-6 py-5">
                          <div className="w-32">
                            <div className="h-2 overflow-hidden rounded-full bg-[var(--ag-surface-2)]">
                              <div
                                className="h-full rounded-full"
                                style={{
                                  width: `${Math.round(averageSurface * 100)}%`,
                                  background:
                                    averageSurface < 0.3
                                      ? "var(--ag-green)"
                                      : averageSurface < 0.6
                                      ? "var(--ag-amber)"
                                      : "var(--ag-red)",
                                }}
                              />
                            </div>
                            <p className="mt-2 font-mono text-xs text-[var(--ag-text-3)]">
                              {Math.round(averageSurface * 100)}%
                            </p>
                          </div>
                        </td>
                        <td className="px-6 py-5">
                          <a href={`/report/${session.session_id}`}>
                            <AGVerdictBadge verdict={verdict} />
                          </a>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </AGSurface>
      </div>
    </main>
  );
}
