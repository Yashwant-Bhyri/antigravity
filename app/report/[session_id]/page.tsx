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
  schema_version?: string;
  overall_score: number | null;
  hire_recommendation: string | null;
  confidence_score: number | null;
  confidence_band?: { low: number; point: number; high: number } | null;
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
  coverage_gate?: { passed: boolean; reasons: string[]; assessment_coverage?: Record<string, any> } | null;
  interview_quality?: {
    score: number;
    band: string;
    role_relevance?: string;
    coverage_breadth?: string;
    tunneling_detected?: boolean;
    fairness_warnings?: string[];
  } | null;
  role_fit_profile?: {
    target_role_fit?: string;
    best_fit_archetype?: string;
    strongest_signal?: string;
    largest_unresolved_risk?: string;
    alternate_fit_notes?: string;
  } | null;
  ability_profile?: {
    strongest_verified_signal?: string;
    weakest_verified_signal?: string;
    alternate_fit_archetypes?: string[];
    target_role_fit?: string;
    role_fit_explanation?: string;
  } | null;
  resume_claim_calibration?: {
    claims_tested?: { claim?: string; hype_level?: string; evidence_strength?: string; claim_risk?: string }[];
    claims_substantiated?: any[];
    claims_partially_substantiated?: any[];
    claims_not_substantiated?: any[];
    claims_untested?: { claim?: string; hype_level?: string }[];
    impact_on_verdict?: string;
    principle?: string;
  } | null;
  tested_strengths?: string[];
  tested_risks?: string[];
  claim_findings?: { claim?: string; status?: string; interpretation?: string; evidence_refs?: any[] }[];
  recommended_followups?: string[];
  candidate_safe_summary?: string | null;
  recruiter_summary?: string | null;
  review_reconciliation?: {
    reviewer_concerns?: string[];
    accepted_changes?: string[];
    rejected_changes?: string[];
    review_model?: string;
  } | null;
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

function titleize(value: string | null | undefined) {
  return String(value ?? "")
    .replace(/_/g, " ")
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

function compactList<T>(items: T[] | undefined | null, limit = 4): T[] {
  return Array.isArray(items) ? items.slice(0, limit) : [];
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
  const reportSummary = report.candidate_safe_summary || report.recruiter_summary || report.summary;
  const v2Report = report.schema_version === "final_report_v2";
  const testedStrengths = report.tested_strengths?.length ? report.tested_strengths : report.strengths;
  const testedRisks = report.tested_risks?.length ? report.tested_risks : report.risk_flags;

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
            {report.confidence_band && (
              <p className="text-xs text-[var(--ag-text-3)]">
                Score band {report.confidence_band.low.toFixed(1)}-{report.confidence_band.high.toFixed(1)}
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
            subtext={v2Report ? "raw probes; interpreted through evidence gates" : "pressure points judged materially weak"}
            emphasis={highSeverityCount > 0 ? "red" : "green"}
          />
          <AGMetricCard
            label="Overall Score"
            value={report.overall_score != null ? `${report.overall_score.toFixed(1)}/10` : "—"}
            subtext="aggregate signal after full synthesis"
            emphasis={metricEmphasis(report.overall_score)}
          />
        </div>

        {report.coverage_gate && !report.coverage_gate.passed && (
          <AGSurface className="border-[oklch(0.8_0.16_72_/_0.22)] px-6 py-5">
            <AGSectionLabel>Assessment Limits</AGSectionLabel>
            <p className="mt-4 max-w-4xl text-sm leading-7 text-[var(--ag-text-1)]">
              This report is constrained by interview coverage. Treat the verdict as an evidence boundary, not a candidate-wide rejection.
            </p>
            <div className="mt-4 flex flex-wrap gap-2">
              {compactList(report.coverage_gate.reasons, 8).map((reason) => (
                <span key={reason} className="rounded-lg border border-[oklch(0.8_0.16_72_/_0.28)] bg-[oklch(0.8_0.16_72_/_0.08)] px-3 py-1 text-xs text-[var(--ag-amber)]">
                  {titleize(reason)}
                </span>
              ))}
            </div>
          </AGSurface>
        )}

        {reportSummary && (
          <AGSurface className="px-6 py-6">
            <AGSectionLabel>Assessment Summary</AGSectionLabel>
            <p className="mt-4 max-w-4xl text-sm leading-7 text-[var(--ag-text-1)]">{reportSummary}</p>
          </AGSurface>
        )}

        {(report.role_fit_profile || report.ability_profile || report.interview_quality) && (
          <div className="grid gap-4 lg:grid-cols-3">
            {report.role_fit_profile && (
              <AGSurface className="px-5 py-5">
                <AGSectionLabel>Role Fit</AGSectionLabel>
                <p className="mt-4 text-2xl font-semibold text-[var(--ag-text-0)]">
                  {titleize(report.role_fit_profile.target_role_fit || report.ability_profile?.target_role_fit || "inconclusive")}
                </p>
                {report.role_fit_profile.strongest_signal && (
                  <p className="mt-3 text-sm leading-6 text-[var(--ag-text-1)]">{report.role_fit_profile.strongest_signal}</p>
                )}
                {report.role_fit_profile.largest_unresolved_risk && (
                  <p className="mt-3 text-xs leading-6 text-[var(--ag-text-3)]">{report.role_fit_profile.largest_unresolved_risk}</p>
                )}
              </AGSurface>
            )}

            {report.ability_profile && (
              <AGSurface className="px-5 py-5">
                <AGSectionLabel>Strongest Signal</AGSectionLabel>
                <p className="mt-4 text-sm leading-7 text-[var(--ag-text-1)]">
                  {report.ability_profile.strongest_verified_signal || "No strong verified signal was isolated."}
                </p>
                {compactList(report.ability_profile.alternate_fit_archetypes, 3).length > 0 && (
                  <div className="mt-4 flex flex-wrap gap-2">
                    {compactList(report.ability_profile.alternate_fit_archetypes, 3).map((fit) => (
                      <span key={fit} className="rounded-lg border border-[var(--ag-border)] px-3 py-1 text-xs text-[var(--ag-text-2)]">{fit}</span>
                    ))}
                  </div>
                )}
              </AGSurface>
            )}

            {report.interview_quality && (
              <AGSurface className="px-5 py-5">
                <AGSectionLabel>Interview Quality</AGSectionLabel>
                <p className="mt-4 text-2xl font-semibold text-[var(--ag-text-0)]">
                  {Math.round(report.interview_quality.score * 100)}%
                </p>
                <p className="mt-2 text-sm text-[var(--ag-text-2)]">{titleize(report.interview_quality.band)}</p>
                {compactList(report.interview_quality.fairness_warnings, 3).length > 0 && (
                  <div className="mt-4 space-y-2">
                    {compactList(report.interview_quality.fairness_warnings, 3).map((warning) => (
                      <p key={warning} className="text-xs leading-5 text-[var(--ag-text-3)]">{titleize(warning)}</p>
                    ))}
                  </div>
                )}
              </AGSurface>
            )}
          </div>
        )}

        {v2Report && (testedStrengths.length > 0 || testedRisks.length > 0) && (
          <div className="grid gap-6 lg:grid-cols-2">
            {testedStrengths.length > 0 && (
              <AGSurface className="px-6 py-6">
                <AGSectionLabel>Tested Strengths</AGSectionLabel>
                <ul className="mt-5 space-y-3 text-sm leading-7 text-[var(--ag-text-1)]">
                  {compactList(testedStrengths, 5).map((strength, index) => (
                    <li key={`${strength}-${index}`} className="rounded-xl border border-[var(--ag-border)] bg-[var(--ag-surface-0)] px-4 py-4">
                      {strength}
                    </li>
                  ))}
                </ul>
              </AGSurface>
            )}

            {testedRisks.length > 0 && (
              <AGSurface className="px-6 py-6">
                <AGSectionLabel>Scoped Tested Risks</AGSectionLabel>
                <ul className="mt-5 space-y-3 text-sm leading-7 text-[var(--ag-text-1)]">
                  {compactList(testedRisks, 5).map((risk, index) => (
                    <li key={`${risk}-${index}`} className="rounded-xl border border-[oklch(0.8_0.16_72_/_0.22)] bg-[oklch(0.8_0.16_72_/_0.07)] px-4 py-4">
                      {risk}
                    </li>
                  ))}
                </ul>
              </AGSurface>
            )}
          </div>
        )}

        {report.resume_claim_calibration && (
          <AGSurface className="px-6 py-6">
            <AGSectionLabel>Resume Claim Calibration</AGSectionLabel>
            <p className="mt-4 max-w-4xl text-sm leading-7 text-[var(--ag-text-1)]">
              {report.resume_claim_calibration.principle || "Resume language guides questioning depth; final judgment comes from tested evidence."}
            </p>
            <div className="mt-5 grid gap-4 md:grid-cols-2">
              {compactList(report.resume_claim_calibration.claims_tested, 4).length > 0 && (
                <div>
                  <p className="mb-2 font-mono text-[10px] uppercase tracking-[0.16em] text-[var(--ag-text-3)]">Tested Claims</p>
                  <ul className="space-y-2">
                    {compactList(report.resume_claim_calibration.claims_tested, 4).map((claim, index) => (
                      <li key={`${claim.claim}-${index}`} className="rounded-lg border border-[var(--ag-border)] px-3 py-3 text-xs leading-5 text-[var(--ag-text-1)]">
                        {claim.claim}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              {compactList(report.resume_claim_calibration.claims_untested, 4).length > 0 && (
                <div>
                  <p className="mb-2 font-mono text-[10px] uppercase tracking-[0.16em] text-[var(--ag-text-3)]">Untested Claims</p>
                  <ul className="space-y-2">
                    {compactList(report.resume_claim_calibration.claims_untested, 4).map((claim, index) => (
                      <li key={`${claim.claim}-${index}`} className="rounded-lg border border-[var(--ag-border)] px-3 py-3 text-xs leading-5 text-[var(--ag-text-1)]">
                        {claim.claim}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          </AGSurface>
        )}

        {report.recommended_followups && report.recommended_followups.length > 0 && (
          <AGSurface className="px-6 py-6">
            <AGSectionLabel>Recommended Follow-Ups</AGSectionLabel>
            <ul className="mt-5 grid gap-3 md:grid-cols-2">
              {compactList(report.recommended_followups, 6).map((item, index) => (
                <li key={`${item}-${index}`} className="rounded-xl border border-[var(--ag-border)] bg-[var(--ag-surface-0)] px-4 py-4 text-sm leading-7 text-[var(--ag-text-1)]">
                  {item}
                </li>
              ))}
            </ul>
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
                        Probe direction: {((weakness.probe_direction ?? (weakness as any).attack_strategy ?? "")).replace(/_/g, " ")}
                      </p>
                    </div>
                  ))}
                </div>
              </AGSurface>
            )}
          </div>

          <div className="space-y-6">
            {!v2Report && report.strengths.length > 0 && (
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

            {!v2Report && report.risk_flags.length > 0 && (
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
