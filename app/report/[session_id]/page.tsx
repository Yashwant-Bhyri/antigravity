import { notFound } from "next/navigation";
import { AGButton, AGMetricCard, AGScoreBar, AGScoreGauge, AGSectionLabel, AGSeverityPip, AGSurface, AGVerdictBadge } from "@/components/design-system";
import { getApiBaseUrl } from "@/lib/api";

type CoveragePortrait = {
  coverage_score: number;
  coverage_confidence: number;
  primary_domain: {
    voluntary_coverage: string[];
    recovered_coverage: string[];
    missed_coverage: string[];
    incorrect_coverage: string[];
    domain_score: number;
  };
};

type Report = {
  session_id: string;
  complete: boolean;
  candidate_name?: string;
  target_role: string;
  years_experience: string;
  total_questions: number;
  overall_score: number | null;
  hire_recommendation: string | null;
  confidence_score: number | null;
  summary: string | null;
  strengths: string[];
  risk_flags: string[];
  untested_dimensions: string[];
  scores: Record<string, number | string>;
  failure_surface: Record<string, number>;
  weakness_summary: Record<string, number>;
  raw_weaknesses: { type: string; severity: string; weakness: string; probe_direction: string }[];
  claim_credibility_risk: { level: string; detail: string } | null;
  coverage_portrait?: CoveragePortrait | null;
  verdict_basis?: string;
  verdict_confidence_basis?: string;
};

async function getReport(sessionId: string): Promise<Report> {
  const res = await fetch(`${getApiBaseUrl()}/report/${sessionId}`, { cache: "no-store" });
  if (!res.ok) notFound();
  return res.json();
}

function isNumericScore(score: number | string): score is number {
  return typeof score === "number" && Number.isFinite(score);
}

function metricEmphasis(value: number | null | undefined) {
  if (typeof value !== "number" || !Number.isFinite(value)) return "default" as const;
  if (value >= 7) return "green" as const;
  if (value >= 4) return "amber" as const;
  return "red" as const;
}

export default async function ReportPage({
  params,
}: {
  params: Promise<{ session_id: string }>;
}) {
  const { session_id } = await params;
  const report = await getReport(session_id);
  const scoreEntries = Object.entries(report.scores ?? {});
  const failureEntries = Object.entries(report.failure_surface ?? {});
  const weaknessSummaryEntries = Object.entries(report.weakness_summary ?? {});
  const highSeverityCount = report.raw_weaknesses.filter((item) => item.severity === "high").length;

  return (
    <main className="ag-shell min-h-screen px-6 py-8 md:px-10">
      <div className="mx-auto flex w-full max-w-6xl flex-col gap-8">
        <div className="flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
          <div className="space-y-4">
            <AGButton href="/dashboard" variant="ghost" className="w-fit px-0 py-0 text-sm">
              ← Dashboard
            </AGButton>
            <div className="space-y-3">
              <AGSectionLabel>Interview Report</AGSectionLabel>
              <div className="flex flex-wrap items-center gap-3">
                <h1 className="text-3xl font-semibold tracking-[-0.04em] text-[var(--ag-text-0)] md:text-5xl">
                  {report.candidate_name ? report.candidate_name : "Interview Assessment Report"}
                </h1>
                <AGVerdictBadge verdict={report.hire_recommendation} size="lg" />
              </div>
              {report.candidate_name && (
                <p className="text-sm text-[var(--ag-text-2)]">Interview Assessment Report</p>
              )}
              <p className="font-mono text-xs text-[var(--ag-text-3)]">{report.session_id}</p>
              <div className="flex flex-wrap gap-2">
                {report.target_role && <span className="rounded-lg border border-[var(--ag-border)] px-3 py-1 text-xs text-[var(--ag-text-2)]">{report.target_role}</span>}
                {report.years_experience && <span className="rounded-lg border border-[var(--ag-border)] px-3 py-1 text-xs text-[var(--ag-text-2)]">{report.years_experience} YOE</span>}
                {!report.complete && <span className="rounded-lg border border-[oklch(0.8_0.16_72_/_0.28)] bg-[oklch(0.8_0.16_72_/_0.08)] px-3 py-1 text-xs text-[var(--ag-amber)]">Partial report</span>}
              </div>
            </div>
          </div>

          <AGSurface className="flex flex-col items-center gap-4 px-6 py-6 md:min-w-[280px]">
            <AGScoreGauge score={report.overall_score} label="overall" size={150} />
            {report.confidence_score != null && (
              <p className="font-mono text-xs uppercase tracking-[0.16em] text-[var(--ag-text-3)]">
                {Math.round(report.confidence_score * 100)}% confidence
              </p>
            )}
          </AGSurface>
        </div>

        <div className="grid gap-4 md:grid-cols-3">
          <AGMetricCard
            label="Questions"
            value={report.total_questions}
            subtext="asked across the full interview"
            emphasis="blue"
          />
          <AGMetricCard
            label="High Severity"
            value={highSeverityCount}
            subtext="pressure points judged materially weak"
            emphasis={highSeverityCount > 0 ? "red" : "green"}
          />
          <AGMetricCard
            label="Overall Score"
            value={report.overall_score != null ? `${report.overall_score.toFixed(1)}/10` : "—"}
            subtext="aggregate signal after full synthesis"
            emphasis={metricEmphasis(report.overall_score)}
          />
        </div>

        {report.summary && (
          <AGSurface className="px-6 py-6">
            <AGSectionLabel>Assessment Summary</AGSectionLabel>
            <p className="mt-4 max-w-4xl text-sm leading-7 text-[var(--ag-text-1)]">{report.summary}</p>
          </AGSurface>
        )}

        {report.coverage_portrait && (
          <AGSurface className="px-6 py-6">
            <AGSectionLabel>Knowledge Coverage</AGSectionLabel>
            <div className="mt-4 flex items-center gap-3">
              <span className="font-mono text-2xl font-semibold text-[var(--ag-text-0)]">
                {Math.round(report.coverage_portrait.coverage_score * 100)}%
              </span>
              <span className="text-sm text-[var(--ag-text-3)]">of expected dimensions addressed</span>
              {report.coverage_portrait.coverage_confidence < 0.6 && (
                <span className="rounded-lg border border-[oklch(0.8_0.16_72_/_0.28)] bg-[oklch(0.8_0.16_72_/_0.08)] px-2 py-0.5 text-xs text-[var(--ag-amber)]">
                  limited domain data
                </span>
              )}
            </div>
            <div className="mt-5 grid gap-4 md:grid-cols-3">
              {report.coverage_portrait.primary_domain.voluntary_coverage.length > 0 && (
                <div>
                  <p className="mb-2 font-mono text-[10px] uppercase tracking-[0.16em] text-[var(--ag-green)]">Demonstrated voluntarily</p>
                  <ul className="space-y-1">
                    {report.coverage_portrait.primary_domain.voluntary_coverage.map((l) => (
                      <li key={l} className="rounded-lg bg-[oklch(0.7_0.17_145_/_0.07)] px-3 py-2 text-xs text-[var(--ag-text-1)]">{l}</li>
                    ))}
                  </ul>
                </div>
              )}
              {report.coverage_portrait.primary_domain.recovered_coverage.length > 0 && (
                <div>
                  <p className="mb-2 font-mono text-[10px] uppercase tracking-[0.16em] text-[var(--ag-amber)]">Recovered when prompted</p>
                  <ul className="space-y-1">
                    {report.coverage_portrait.primary_domain.recovered_coverage.map((l) => (
                      <li key={l} className="rounded-lg bg-[oklch(0.8_0.16_72_/_0.07)] px-3 py-2 text-xs text-[var(--ag-text-1)]">{l}</li>
                    ))}
                  </ul>
                </div>
              )}
              {report.coverage_portrait.primary_domain.missed_coverage.length > 0 && (
                <div>
                  <p className="mb-2 font-mono text-[10px] uppercase tracking-[0.16em] text-[var(--ag-red)]">Not addressed</p>
                  <ul className="space-y-1">
                    {report.coverage_portrait.primary_domain.missed_coverage.map((l) => (
                      <li key={l} className="rounded-lg bg-[oklch(0.66_0.21_24_/_0.07)] px-3 py-2 text-xs text-[var(--ag-text-1)]">{l}</li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
            {report.verdict_confidence_basis && (
              <p className="mt-4 text-xs text-[var(--ag-text-3)]">{report.verdict_confidence_basis}</p>
            )}
          </AGSurface>
        )}

        {report.claim_credibility_risk && report.claim_credibility_risk.level !== "not_tested" && (
          <AGSurface className="border-[oklch(0.8_0.16_72_/_0.2)] px-6 py-5">
            <AGSectionLabel>Resume Claim Credibility</AGSectionLabel>
            <div className="mt-3 flex flex-wrap items-center gap-3">
              <AGVerdictBadge verdict={`${report.claim_credibility_risk.level.toUpperCase()} RISK`} />
            </div>
            <p className="mt-4 text-sm leading-7 text-[var(--ag-text-1)]">{report.claim_credibility_risk.detail}</p>
          </AGSurface>
        )}

        <div className="grid gap-6 xl:grid-cols-[1.15fr_0.85fr]">
          <div className="space-y-6">
            {scoreEntries.length > 0 && (
              <AGSurface className="px-6 py-6">
                <AGSectionLabel>Score Breakdown</AGSectionLabel>
                <div className="mt-5 space-y-4">
                  {scoreEntries.map(([dimension, score]) =>
                    isNumericScore(score) ? (
                      <AGScoreBar key={dimension} label={dimension} score={score} />
                    ) : (
                      <div key={dimension} className="rounded-xl border border-[var(--ag-border)] bg-[var(--ag-surface-0)] px-4 py-4">
                        <div className="flex items-center justify-between gap-4">
                          <span className="capitalize text-[var(--ag-text-1)]">{dimension.replace(/_/g, " ")}</span>
                          <span className="font-mono text-xs text-[var(--ag-text-3)]">{String(score)}</span>
                        </div>
                        <p className="mt-3 text-xs leading-6 text-[var(--ag-text-3)]">
                          This dimension did not have enough coverage to score numerically.
                        </p>
                      </div>
                    ),
                  )}
                </div>
              </AGSurface>
            )}

            {failureEntries.length > 0 && (
              <AGSurface className="px-6 py-6">
                <AGSectionLabel>Knowledge Boundary Map</AGSectionLabel>
                <p className="mt-3 text-xs text-[var(--ag-text-3)]">Higher means the candidate broke earlier under pressure.</p>
                <div className="mt-5 space-y-4">
                  {failureEntries.map(([area, score]) => {
                    const pct = Math.round(score * 100);
                    const barColor = score >= 0.6 ? "var(--ag-red)" : score >= 0.35 ? "var(--ag-amber)" : "var(--ag-green)";
                    return (
                      <div key={area} className="space-y-2">
                        <div className="flex items-center justify-between gap-4">
                          <span className="capitalize text-sm text-[var(--ag-text-1)]">{area.replace(/_/g, " ")}</span>
                          <span className="font-mono text-xs text-[var(--ag-text-3)]">{pct}%</span>
                        </div>
                        <div className="h-2 overflow-hidden rounded-full bg-[var(--ag-surface-2)]">
                          <div className="h-full rounded-full" style={{ width: `${pct}%`, background: barColor, boxShadow: `0 0 12px ${barColor}` }} />
                        </div>
                      </div>
                    );
                  })}
                </div>
              </AGSurface>
            )}

            {report.raw_weaknesses.length > 0 && (
              <AGSurface className="px-6 py-6">
                <AGSectionLabel>Probing Points</AGSectionLabel>
                {weaknessSummaryEntries.length > 0 && (
                  <div className="mt-5 flex flex-wrap gap-2">
                    {weaknessSummaryEntries.map(([type, count]) => (
                      <span
                        key={type}
                        className="rounded-lg border border-[var(--ag-border)] bg-[var(--ag-surface-0)] px-3 py-2 font-mono text-[10px] uppercase tracking-[0.14em] text-[var(--ag-text-2)]"
                      >
                        {type.replace(/_/g, " ")}: {count}
                      </span>
                    ))}
                  </div>
                )}
                <div className="mt-5 space-y-3">
                  {report.raw_weaknesses.map((weakness, index) => (
                    <div
                      key={`${weakness.weakness}-${index}`}
                      className="rounded-xl border border-[var(--ag-border)] bg-[var(--ag-surface-0)] px-4 py-4"
                    >
                      <div className="flex flex-wrap items-center gap-2">
                        <AGSeverityPip severity={weakness.severity} />
                        <span className="font-mono text-[10px] uppercase tracking-[0.16em] text-[var(--ag-text-3)]">
                          {weakness.severity} · {weakness.type.replace(/_/g, " ")}
                        </span>
                      </div>
                      <p className="mt-3 text-sm leading-7 text-[var(--ag-text-0)]">{weakness.weakness}</p>
                      <p className="mt-2 text-xs uppercase tracking-[0.12em] text-[var(--ag-text-3)]">
                        Probe direction: {(weakness.probe_direction ?? "").replace(/_/g, " ")}
                      </p>
                    </div>
                  ))}
                </div>
              </AGSurface>
            )}
          </div>

          <div className="space-y-6">
            {report.strengths.length > 0 && (
              <AGSurface className="px-6 py-6">
                <AGSectionLabel>Strengths</AGSectionLabel>
                <ul className="mt-5 space-y-3 text-sm leading-7 text-[var(--ag-text-1)]">
                  {report.strengths.map((strength, index) => (
                    <li key={`${strength}-${index}`} className="rounded-xl border border-[var(--ag-border)] bg-[var(--ag-surface-0)] px-4 py-4">
                      {strength}
                    </li>
                  ))}
                </ul>
              </AGSurface>
            )}

            {report.risk_flags.length > 0 && (
              <AGSurface className="px-6 py-6">
                <AGSectionLabel>Risk Flags</AGSectionLabel>
                <ul className="mt-5 space-y-3 text-sm leading-7 text-[var(--ag-text-1)]">
                  {report.risk_flags.map((flag, index) => (
                    <li
                      key={`${flag}-${index}`}
                      className="rounded-xl border border-[oklch(0.66_0.21_24_/_0.22)] bg-[oklch(0.66_0.21_24_/_0.08)] px-4 py-4"
                    >
                      {flag}
                    </li>
                  ))}
                </ul>
              </AGSurface>
            )}

            {report.untested_dimensions.length > 0 && (
              <AGSurface className="px-6 py-6">
                <AGSectionLabel>Untested Dimensions</AGSectionLabel>
                <ul className="mt-5 space-y-3 text-sm leading-7 text-[var(--ag-text-1)]">
                  {report.untested_dimensions.map((dimension, index) => (
                    <li key={`${dimension}-${index}`} className="rounded-xl border border-[var(--ag-border)] bg-[var(--ag-surface-0)] px-4 py-4">
                      {dimension}
                    </li>
                  ))}
                </ul>
              </AGSurface>
            )}
          </div>
        </div>
      </div>
    </main>
  );
}
