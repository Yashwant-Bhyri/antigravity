import type {
  ClaimFinding,
  CoverageItem,
  DemoReport,
  DimensionScore,
  EvidenceTurn,
  ReportTone,
  WeaknessFinding,
} from "../demo-reports/report-data";

type JsonRecord = Record<string, unknown>;

const record = (value: unknown): JsonRecord =>
  value && typeof value === "object" && !Array.isArray(value) ? (value as JsonRecord) : {};

const list = (value: unknown): unknown[] => (Array.isArray(value) ? value : []);

const text = (value: unknown, fallback = "") => {
  const result = typeof value === "string" ? value.trim() : "";
  return result || fallback;
};

const userFacingText = (value: unknown, fallback = "") => {
  const result = text(value);
  if (!result) return fallback;
  // Internal route/prompt/schema tokens are audit metadata, not report copy.
  if (/^[a-z0-9]+(?:_[a-z0-9]+){2,}$/i.test(result)) return fallback;
  return result
    .replace(/\bLLM verdict\b/gi, "Model evidence interpretation")
    .replace(/\bhiring verdict\b/gi, "interview evidence state")
    .replace(/\bhire recommendation\b/gi, "interview evidence interpretation");
};

const number = (value: unknown, fallback = 0) => {
  const result = typeof value === "number" ? value : Number(value);
  return Number.isFinite(result) ? result : fallback;
};

const titleize = (value: unknown) =>
  text(value, "Not measured")
    .replace(/[_-]+/g, " ")
    .replace(/\b\w/g, (character) => character.toUpperCase());

const clampScore = (value: unknown, fallback = 0) => Math.max(0, Math.min(10, number(value, fallback)));

const normalizedRatio = (value: unknown, fallback = 0) => {
  const raw = number(value, fallback);
  return Math.max(0, Math.min(1, raw > 1 ? raw / 10 : raw));
};

const stringList = (value: unknown) =>
  list(value)
    .map((item) => (typeof item === "string" ? item.trim() : text(record(item).detail) || text(record(item).label)))
    .filter(Boolean);

const toneFor = (score: number, verdict: string): ReportTone => {
  const lower = verdict.toLowerCase();
  if (lower.includes("strong") || score >= 8.5) return "elite";
  if (lower.includes("no hire") || score < 4.5) return "risk";
  if (lower.includes("maybe") || lower.includes("insufficient")) return "mixed";
  return "emerging";
};

const evidenceStatusFor = (value: unknown, complete: unknown) => {
  const legacy = text(value).toUpperCase().replace(/_/g, " ");
  if (legacy.includes("INSUFFICIENT")) return "INSUFFICIENT INTERVIEW EVIDENCE";
  if (legacy.includes("NO HIRE")) return "LIMITED INTERVIEW EVIDENCE";
  if (legacy.includes("MAYBE") || legacy.includes("FOLLOW UP"))
    return "MIXED INTERVIEW EVIDENCE";
  if (legacy.includes("HIRE")) return "SUBSTANTIAL INTERVIEW EVIDENCE";
  // Replay sessions can report `complete: false` even when they materialize a
  // retained final report. A source interpretation, when present, is therefore
  // the canonical evidence state; completion is only a fallback signal.
  if (complete === false) return "INSUFFICIENT INTERVIEW EVIDENCE";
  return "ASSESSMENT EVIDENCE RECORDED";
};

const claimStatus = (value: unknown): ClaimFinding["status"] => {
  const status = text(value).toLowerCase().replace(/\s+/g, "_");
  if (status.includes("not_substantiated") || status === "failed") return "not_substantiated";
  if (status.includes("partial")) return "partial";
  if (status.includes("substantiated") || status === "verified") return "substantiated";
  return "untested";
};

const severity = (value: unknown): WeaknessFinding["severity"] => {
  const level = text(value).toLowerCase();
  return level === "high" || level === "low" ? level : "medium";
};

export function adaptProductionReport(payload: JsonRecord, sessionId: string): DemoReport {
  const scoresObject = record(payload.scores);
  const breakdown = Object.keys(scoresObject).length ? scoresObject : record(payload.breakdown);
  const overallScore = clampScore(payload.overall_score, 0);
  const verdict = text(
    payload.evidence_status,
    evidenceStatusFor(payload.hire_recommendation, payload.complete),
  );
  const roleFit = record(payload.role_fit_profile);
  const ability = record(payload.ability_profile);
  const coveragePortrait = record(payload.coverage_portrait);
  const primaryDomain = record(coveragePortrait.primary_domain);
  const quality = record(payload.interview_quality);
  const credibility = record(payload.claim_credibility_risk);
  const history = list(payload.history).map(record);
  const perAnswerScores = list(payload.per_answer_scores).map(record);

  const mappedScores: DimensionScore[] = Object.entries(breakdown)
    .filter(([, value]) => Number.isFinite(Number(value)))
    .slice(0, 8)
    .map(([label, value]) => ({
      label: titleize(label),
      score: clampScore(value),
      note: `Measured from the final evidence packet: ${clampScore(value).toFixed(1)}/10.`,
    }));

  const fallbackScores: DimensionScore[] = [
    { label: "Technical depth", score: overallScore, note: "Overall evidence-weighted interview score." },
    { label: "Reasoning structure", score: overallScore, note: "No separate dimension was emitted." },
    { label: "Communication", score: overallScore, note: "No separate dimension was emitted." },
  ];
  const scores = mappedScores.length ? mappedScores : fallbackScores;

  const coverage: CoverageItem[] = [
    ...stringList(primaryDomain.voluntary_coverage).map((label) => ({ label, state: "voluntary" as const, detail: "Demonstrated without recovery prompting." })),
    ...stringList(primaryDomain.recovered_coverage).map((label) => ({ label, state: "recovered" as const, detail: "Demonstrated after targeted recovery prompting." })),
    ...stringList(primaryDomain.missed_coverage).map((label) => ({ label, state: "missed" as const, detail: "Not demonstrated when tested." })),
    ...stringList(primaryDomain.incorrect_coverage).map((label) => ({ label, state: "incorrect" as const, detail: "Evidence was materially incorrect." })),
  ];

  const claims = list(payload.claim_findings).map(record).map((item): ClaimFinding => ({
    claim: text(item.claim, "Resume claim"),
    status: claimStatus(item.status),
    evidence: text(item.interpretation, text(item.evidence, "See linked evidence references in the source packet.")),
  }));

  const riskFlags = stringList(payload.tested_risks).length
    ? stringList(payload.tested_risks)
    : stringList(payload.risk_flags);
  const followups = stringList(payload.recommended_followups);
  const rawWeaknesses = list(payload.raw_weaknesses).map(record);
  const weaknesses = rawWeaknesses.length
    ? rawWeaknesses.map((item): WeaknessFinding => ({
        area: titleize(item.type || item.area),
        severity: severity(item.severity),
        trigger: text(item.weakness, text(item.trigger, "Observed during a pressure probe.")),
        interpretation: text(item.interpretation, text(item.weakness, "This signal needs targeted follow-up.")),
        followup: text(item.probe_direction, "Ask for a concrete mechanism, failure boundary, and verification evidence."),
      }))
    : riskFlags.map((risk, index): WeaknessFinding => ({
        area: `Retained risk ${index + 1}`,
        severity: "medium",
        trigger: risk,
        interpretation: "The saved final report retained this as an unresolved interview signal; do not infer more than the source states.",
        followup: followups[index] || "Ask for a concrete mechanism, failure boundary, test, and ownership evidence.",
      }));

  const timeline: EvidenceTurn[] = history.map((item, index) => {
    const scored = perAnswerScores[index] || {};
    const rawScore = scored.overall_score ?? scored.score;
    const scoreAvailable = Number.isFinite(Number(rawScore));
    return {
      turn: `T${index + 1}`,
      route: titleize(item.route_kind || item.agenda_phase || "Interview probe"),
      signal: titleize(scored.signal || scored.answer_bucket || "Recorded evidence"),
      question: text(item.question, text(item.prompt, text(item.ai_question))),
      observation: text(scored.rationale, text(item.answer, "Response captured in the interview transcript.")),
      score: scoreAvailable ? clampScore(rawScore) : 0,
      scoreAvailable,
    };
  });

  const safeTimeline = timeline.length
    ? timeline
    : [{ turn: "T1", route: "Final synthesis", signal: "Saved report", observation: text(payload.summary, "Saved report evidence."), score: 0, scoreAvailable: false }];
  const strengths = stringList(payload.tested_strengths).length ? stringList(payload.tested_strengths) : stringList(payload.strengths);
  const risks = riskFlags;
  const confidence = normalizedRatio(payload.confidence_score, 0);
  const coverageScore = normalizedRatio(coveragePortrait.coverage_score, 0);
  const interviewQuality = normalizedRatio(quality.score, coverageScore);
  const candidate = text(payload.candidate_name, "Candidate");
  const summary = text(payload.recruiter_summary, text(payload.summary, "The final report has been saved, but no narrative summary was emitted."));

  return {
    sourceKind: "production",
    slug: sessionId,
    tone: toneFor(overallScore, verdict),
    candidate,
    headline: text(roleFit.strongest_signal, text(ability.strongest_verified_signal, summary)),
    targetRole: text(payload.target_role, "Target role not specified"),
    experience: text(payload.years_experience, "Experience not specified"),
    verdict,
    score: overallScore,
    confidence,
    questions: history.length,
    duration: text(payload.duration, "Recorded session"),
    summary,
    executiveRead: userFacingText(payload.verdict_basis, userFacingText(payload.verdict_confidence_basis, summary)),
    strongestSignal: text(roleFit.strongest_signal, text(ability.strongest_verified_signal, strengths[0] || "No verified strength was emitted.")),
    largestRisk: text(roleFit.largest_unresolved_risk, text(ability.weakest_verified_signal, risks[0] || "No material risk was emitted.")),
    interviewQuality,
    coverageScore,
    claimRisk: severity(credibility.level),
    roleFit: titleize(roleFit.target_role_fit || ability.target_role_fit || "Role fit not assessed"),
    archetype: text(roleFit.best_fit_archetype, stringList(ability.alternate_fit_archetypes)[0] || "Evidence-led candidate profile"),
    scores,
    radar: scores.slice(0, 6),
    coverage: coverage.length ? coverage : [{ label: "Coverage unavailable", state: "missed", detail: "The source report did not include a coverage portrait." }],
    strengths: strengths.length ? strengths : ["No tested strength was emitted by the source report."],
    risks: risks.length ? risks : ["No tested risk was emitted by the source report."],
    claims: claims.length ? claims : [{ claim: "Resume claims", status: "untested", evidence: text(credibility.detail, "No claim-level findings were emitted.") }],
    weaknesses: weaknesses.length ? weaknesses : [{ area: "Not assessed", severity: "low", trigger: "No weakness-level evidence was retained in this artifact.", interpretation: "Do not infer a weakness from missing structured evidence.", followup: "Collect a targeted follow-up only if the employer rubric requires this dimension." }],
    timeline: safeTimeline,
    transcriptEvidence: history.map((item) => text(item.answer)).filter(Boolean).slice(0, 12),
    recommendedFollowups: followups.length ? followups : weaknesses.map((item) => item.followup).slice(0, 4),
    hiringPanelNotes: [userFacingText(payload.verdict_confidence_basis), userFacingText(payload.verdict_basis), ...stringList(record(payload.review_reconciliation).reviewer_concerns).map((item) => userFacingText(item))].filter(Boolean),
  };
}
