"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import type { ClaimFinding, CoverageItem, DemoReport, DimensionScore, WeaknessFinding } from "../report-data";

type Lens = "decision" | "responsibilities" | "evidence" | "risks" | "next";

type ResponsibilityFit = {
  label: string;
  score: number;
  status: "Ready" | "Supported" | "Avoid";
  detail: string;
};

type HeatmapRow = {
  area: string;
  mechanism: number;
  pressure: number;
  ownership: number;
  risk: number;
};

const UNAVAILABLE_HEATMAP: HeatmapRow = {
  area: "Heat map unavailable",
  mechanism: 0,
  pressure: 0,
  ownership: 0,
  risk: 0,
};

type RubricItem = {
  label: string;
  value: string;
  tone: "green" | "amber" | "red" | "cyan" | "slate";
};

const lensLabels: Record<Lens, string> = {
  decision: "Evidence status",
  responsibilities: "Responsibilities",
  evidence: "Evidence",
  risks: "Risk",
  next: "Next actions",
};

const lensMeta: Record<Lens, { description: string; outcome: string }> = {
  decision: {
    description: "Start here to understand the interview evidence state, coverage limits, and the strongest supported and unresolved signals.",
    outcome: "Shows what the interview can and cannot establish.",
  },
  responsibilities: {
    description: "Use this to inspect each employer-approved responsibility, its supporting evidence, conditions, and unresolved gaps.",
    outcome: "Available only when an explicit employer role rubric is attached.",
  },
  evidence: {
    description: "Use this to inspect the probes, heatmap, coverage, and observed behavior that produced the report's conclusions.",
    outcome: "Connects every judgment back to interview evidence.",
  },
  risks: {
    description: "Use this to locate the exact unresolved weaknesses, claim risks, and follow-up probes needed before human review.",
    outcome: "Prevents vague concerns from becoming hidden evidence risk.",
  },
  next: {
    description: "Use this when the panel needs a clear action package: what to ask next, what to validate, and what evidence to document.",
    outcome: "Turns the report into a concrete evidence workflow.",
  },
};

const toneAccent = {
  elite: "#059669",
  emerging: "#0891b2",
  risk: "#e11d48",
  mixed: "#d97706",
};

const toneBadge = {
  elite: "border-emerald-200 bg-emerald-50 text-emerald-800",
  emerging: "border-cyan-200 bg-cyan-50 text-cyan-800",
  risk: "border-rose-200 bg-rose-50 text-rose-800",
  mixed: "border-amber-200 bg-amber-50 text-amber-800",
};

export function RecruiterWorkspace({
  report,
  nextReports,
  galleryHref = "/demo-reports",
  candidateHref = `/demo-reports/${report.slug}/candidate`,
  galleryLabel = "Demo reports",
}: {
  report: DemoReport;
  nextReports: DemoReport[];
  galleryHref?: string;
  candidateHref?: string;
  galleryLabel?: string;
}) {
  const [lens, setLens] = useState<Lens>("decision");
  const [selectedHeat, setSelectedHeat] = useState(0);
  const [selectedWeakness, setSelectedWeakness] = useState(0);
  const [selectedTurn, setSelectedTurn] = useState(report.timeline.length - 1);

  const responsibilities = useMemo(() => responsibilityFitFor(report), [report]);
  const heatmap = useMemo(() => heatmapFor(report), [report]);
  const selectedHeatRow = heatmap[selectedHeat] ?? UNAVAILABLE_HEATMAP;
  const strongest = report.radar.reduce((best, item) => (item.score > best.score ? item : best), report.radar[0]);
  const weakest = report.radar.reduce((worst, item) => (item.score < worst.score ? item : worst), report.radar[0]);
  const accent = toneAccent[report.tone];

  return (
    <main className="min-h-screen bg-[linear-gradient(180deg,#f6faf9_0%,#eef4f6_45%,#fbfbfb_100%)] text-slate-950">
      <div className="mx-auto flex w-full max-w-[1540px] min-w-0 flex-col gap-5 px-4 py-5 md:px-8">
        <nav className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-slate-200 bg-white px-4 py-3 shadow-sm">
          <Link href={galleryHref} className="group inline-flex items-center gap-3 hover:text-slate-950">
            <ProductMark />
            <span className="font-mono text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500 group-hover:text-slate-950">{galleryLabel}</span>
          </Link>
          <div className="flex flex-wrap gap-2">
            <Link
              href={candidateHref}
              className="rounded-md border border-emerald-200 bg-emerald-50 px-3 py-1.5 text-xs font-semibold text-emerald-800 hover:bg-white"
            >
              Candidate reflection
            </Link>
            {nextReports.map((item) => (
              <Link key={item.slug} href={`/demo-reports/${item.slug}`} className="rounded-md border border-slate-200 bg-slate-50 px-3 py-1.5 text-xs text-slate-600 hover:bg-white">
                {item.candidate}
              </Link>
            ))}
          </div>
        </nav>

        <section>
          <div className="overflow-hidden rounded-lg border border-slate-200 bg-white shadow-sm">
            <div className="grid gap-5 border-b border-slate-200 bg-[#f8fbfb] p-5 md:p-6 lg:grid-cols-[minmax(0,1fr)_170px]">
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <span className={`rounded-md border px-3 py-1.5 font-mono text-[10px] font-semibold uppercase tracking-[0.16em] ${toneBadge[report.tone]}`}>
                    {report.verdict}
                  </span>
                  <span className="rounded-md border border-slate-200 bg-white px-3 py-1.5 font-mono text-[10px] uppercase tracking-[0.16em] text-slate-500">
                    {report.duration} / {report.questions} probes
                  </span>
                </div>
                <p className="mt-5 font-mono text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500">Recruiter assessment report</p>
                <h1 className="mt-2 text-4xl font-semibold text-slate-950 md:text-6xl">{report.candidate}</h1>
                <p className="mt-3 max-w-4xl text-base leading-7 text-slate-600">{report.headline}</p>
                <div className="mt-4 flex flex-wrap gap-2">
                  {[report.targetRole, report.experience, report.roleFit, report.archetype].map((item) => (
                    <span key={item} className="rounded-md border border-slate-200 bg-white px-3 py-1.5 text-xs text-slate-600">{item}</span>
                  ))}
                </div>
              </div>
              <ScoreDial score={report.score} color={accent} />
            </div>

            <div className="grid border-b border-slate-200 bg-white md:grid-cols-4">
              <HeroStat label="Source-reported evidence confidence" value={report.confidence ? `${Math.round(report.confidence * 100)}%` : "Not calibrated"} />
              <HeroStat label="Coverage" value={`${Math.round(report.coverageScore * 100)}%`} />
              <HeroStat label="Claim risk" value={report.claimRisk.toUpperCase()} />
              <HeroStat label="Interview quality" value={`${Math.round(report.interviewQuality * 100)}%`} />
            </div>

            <ReportSignalVisualization report={report} responsibilities={responsibilities} heatmap={heatmap} accent={accent} />
            <LensNavigation lens={lens} setLens={setLens} />
          </div>
        </section>

        <section className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_360px]">
          <div className="min-w-0">
            <RecruiterFullReport
              report={report}
              lens={lens}
              accent={accent}
              responsibilities={responsibilities}
              heatmap={heatmap}
              selectedHeat={selectedHeat}
              setSelectedHeat={setSelectedHeat}
              selectedTurn={selectedTurn}
              setSelectedTurn={setSelectedTurn}
              selectedWeakness={selectedWeakness}
              setSelectedWeakness={setSelectedWeakness}
            />
          </div>
          <RecruiterSideRail
            report={report}
            lens={lens}
            strongest={strongest}
            weakest={weakest}
            heat={selectedHeatRow}
            weakness={report.weaknesses[selectedWeakness]}
            turn={report.timeline[selectedTurn]}
          />
        </section>
      </div>
    </main>
  );
}

function RecruiterFullReport({
  report,
  lens,
  accent,
  responsibilities,
  heatmap,
  selectedHeat,
  setSelectedHeat,
  selectedTurn,
  setSelectedTurn,
  selectedWeakness,
  setSelectedWeakness,
}: {
  report: DemoReport;
  lens: Lens;
  accent: string;
  responsibilities: ResponsibilityFit[];
  heatmap: HeatmapRow[];
  selectedHeat: number;
  setSelectedHeat: (index: number) => void;
  selectedTurn: number;
  setSelectedTurn: (index: number) => void;
  selectedWeakness: number;
  setSelectedWeakness: (index: number) => void;
}) {
  return (
    <div className="grid gap-5">
      <LensFocusPanel
        report={report}
        lens={lens}
        responsibilities={responsibilities}
        heat={heatmap[selectedHeat] ?? UNAVAILABLE_HEATMAP}
        weakness={report.weaknesses[selectedWeakness]}
        turn={report.timeline[selectedTurn]}
      />
      <RecruiterTrajectoryAnalytics report={report} responsibilities={responsibilities} heatmap={heatmap} />
      <DecisionLens report={report} accent={accent} />
      <ResponsibilityLens responsibilities={responsibilities} report={report} />
      <EvidenceLens
        report={report}
        heatmap={heatmap}
        selectedHeat={selectedHeat}
        setSelectedHeat={setSelectedHeat}
        selectedTurn={selectedTurn}
        setSelectedTurn={setSelectedTurn}
      />
      <RiskLens report={report} selectedWeakness={selectedWeakness} setSelectedWeakness={setSelectedWeakness} />
      <NextLens report={report} />
    </div>
  );
}

function ProductMark() {
  return (
    <span className="inline-flex items-center gap-2">
      <span className="flex h-8 w-8 items-center justify-center rounded-md bg-slate-950 font-mono text-xs font-semibold text-white shadow-sm">AG</span>
      <span className="text-sm font-semibold text-slate-950">Antigravity</span>
    </span>
  );
}

function LensNavigation({ lens, setLens }: { lens: Lens; setLens: (lens: Lens) => void }) {
  return (
    <section className="border-t border-slate-200 bg-white p-4 md:p-5" aria-label="Recruiter report navigation">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="font-mono text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500">Report navigation</p>
          <p className="mt-1 max-w-3xl text-sm leading-6 text-slate-600">
            Choose a report view to update the summary, side context, and highlighted evidence. The full report remains below, so this is a guided way to inspect the same assessment from different evidence angles.
          </p>
        </div>
        <span className="rounded-md border border-cyan-200 bg-cyan-50 px-3 py-2 text-xs font-semibold text-cyan-900">
          Currently viewing: {lensLabels[lens]}
        </span>
      </div>
      <div className="mt-4 grid gap-3 lg:grid-cols-5">
        {(Object.keys(lensLabels) as Lens[]).map((item, index) => {
          const active = lens === item;
          return (
            <button
              key={item}
              type="button"
              data-testid={`recruiter-lens-${item}`}
              onClick={() => setLens(item)}
              className={`group min-h-[176px] rounded-lg border p-4 text-left transition ${
                active
                  ? "border-slate-950 bg-slate-950 text-white shadow-lg shadow-slate-950/10"
                  : "border-slate-200 bg-slate-50 text-slate-700 hover:border-slate-400 hover:bg-white hover:shadow-sm"
              }`}
            >
              <span className={`flex h-8 w-8 items-center justify-center rounded-md font-mono text-xs font-semibold ${active ? "bg-white text-slate-950" : "bg-white text-slate-600"}`}>
                {index + 1}
              </span>
              <span className="mt-4 block text-base font-semibold">{lensLabels[item]}</span>
              <span className={`mt-2 block text-xs leading-5 ${active ? "text-slate-200" : "text-slate-600"}`}>{lensMeta[item].description}</span>
              <span className={`mt-3 block border-t pt-3 text-[11px] font-semibold leading-5 ${active ? "border-white/20 text-cyan-100" : "border-slate-200 text-slate-500"}`}>
                {lensMeta[item].outcome}
              </span>
            </button>
          );
        })}
      </div>
    </section>
  );
}

function ReportSignalVisualization({
  report,
  responsibilities,
  heatmap,
  accent,
}: {
  report: DemoReport;
  responsibilities: ResponsibilityFit[];
  heatmap: HeatmapRow[];
  accent: string;
}) {
  const readyWork = responsibilities.length
    ? responsibilities.filter((item) => item.status === "Ready").length / responsibilities.length
    : null;
  const avgEvidence = heatmap.length
    ? heatmap.reduce((sum, row) => sum + row.mechanism + row.pressure + row.ownership + (10 - row.risk), 0) / (heatmap.length * 4)
    : null;
  const claimIntegrity = report.scores.find((item) => item.label === "Claim integrity")?.score;
  const productionRead = report.scores.find((item) => item.label === "Production awareness")?.score;
  const chart = [
    ...(report.confidence > 0 ? [{
      label: "Source-reported evidence confidence",
      value: report.confidence * 10,
      explanation: "The source model's confidence in its interview-evidence interpretation. This is not calibrated hiring confidence.",
    }] : []),
    {
      label: "Interview coverage",
      value: report.coverageScore * 10,
      explanation: "Share of the expected interview evidence that the source report says was addressed.",
    },
    ...(readyWork == null ? [] : [{
      label: "Responsibilities with sufficient evidence",
      value: readyWork * 10,
      explanation: "Share of employer-approved responsibilities whose configured evidence threshold was met in this interview.",
    }]),
    ...(avgEvidence == null ? [] : [{
      label: "Evidence quality across probes",
      value: avgEvidence,
      explanation: "Combined read of mechanism, pressure handling, ownership, and low residual risk across heatmap areas.",
    }]),
    ...(claimIntegrity == null || productionRead == null ? [] : [{
      label: "Claim integrity and production proof",
      value: (claimIntegrity + productionRead) / 2,
      explanation: "How well resume claims survived probing and whether the candidate showed realistic production judgment.",
    }]),
  ];
  return (
    <section className="border-b border-slate-200 bg-[#fbfdfd] p-4 md:p-5">
      <div className="grid gap-5 xl:grid-cols-[0.75fr_1.25fr] xl:items-center">
        <div>
          <p className="font-mono text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500">Visual evidence map</p>
          <h2 className="mt-2 text-2xl font-semibold text-slate-950">A quick map of the evidence that was actually retained.</h2>
          <p className="mt-2 text-sm leading-6 text-slate-600">
            This visualization is not a separate score. It shows only the available derived signals; missing metrics remain missing and are not filled from the overall interview score.
          </p>
        </div>
        <div className="grid gap-3 md:grid-cols-2">
          {chart.map((item) => (
            <div key={item.label} className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
              <div className="flex items-start justify-between gap-3">
                <p className="text-sm font-semibold leading-5 text-slate-950">{item.label}</p>
                <span className="font-mono text-sm font-semibold text-slate-800">{item.value.toFixed(1)}</span>
              </div>
              <div className="mt-3 h-2 overflow-hidden rounded-full bg-slate-200">
                <div className="h-full rounded-full" style={{ width: `${Math.max(4, Math.min(100, item.value * 10))}%`, background: item.value >= 8 ? accent : scoreColor(item.value) }} />
              </div>
              <p className="mt-3 text-xs leading-5 text-slate-600">{item.explanation}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

function DecisionLens({ report, accent }: { report: DemoReport; accent: string }) {
  return (
    <div className="grid gap-5">
      <Panel title="Executive read">
        <p className="text-sm leading-7 text-slate-700">{report.summary}</p>
        <div className="mt-5 rounded-lg border border-slate-200 bg-slate-50 p-4">
          <p className="font-mono text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-500">Pitch interpretation</p>
          <p className="mt-2 text-sm leading-7 text-slate-700">{report.executiveRead}</p>
        </div>
        <ExecutiveSignalHighlights report={report} />
      </Panel>
      <div className="grid gap-5 lg:grid-cols-2">
        <SignalCard label="Strongest verified signal" value={report.strongestSignal} tone="green" />
        <SignalCard label="Largest unresolved risk" value={report.largestRisk} tone={report.tone === "risk" ? "red" : "amber"} />
      </div>
      <Panel title="Score breakdown">
        <div className="grid gap-3 md:grid-cols-2">
          {report.scores.map((item) => <ScoreBar key={item.label} item={item} color={accent} />)}
        </div>
      </Panel>
    </div>
  );
}

function ExecutiveSignalHighlights({ report }: { report: DemoReport }) {
  const items = [
    {
      title: "Strongest verified signal the panel should remember",
      label: "Starred strength",
      value: report.strongestSignal,
      detail: "This is the clearest positive interview evidence because it survived probing and can be cited with its source limitations.",
      tone: "green" as const,
    },
    {
      title: "Largest unresolved signal that still needs validation",
      label: "Starred risk",
      value: report.largestRisk,
      detail: "This is the biggest reason to add a follow-up probe or work sample before treating the interview evidence as settled.",
      tone: report.tone === "risk" ? "red" as const : "amber" as const,
    },
  ];
  return (
    <div className="mt-5 grid gap-4 lg:grid-cols-2">
      {items.map((item) => (
        <div key={item.title} className={`rounded-lg border p-4 shadow-sm ${detailSurface(item.tone)}`}>
          <div className="flex items-start gap-3">
            <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-slate-950 font-mono text-sm font-semibold text-white">*</span>
            <div>
              <p className="font-mono text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-500">{item.label}</p>
              <h3 className="mt-2 text-lg font-semibold leading-6 text-slate-950">{item.title}</h3>
              <p className="mt-2 text-sm font-semibold leading-6 text-slate-900">{item.value}</p>
              <p className="mt-2 text-xs leading-5 text-slate-700">{item.detail}</p>
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}

function RecruiterTrajectoryAnalytics({
  report,
  responsibilities,
  heatmap,
}: {
  report: DemoReport;
  responsibilities: ResponsibilityFit[];
  heatmap: HeatmapRow[];
}) {
  const sortedTimeline = [...report.timeline].sort((a, b) => Number.parseInt(String(a.turn), 10) - Number.parseInt(String(b.turn), 10));
  const scoredTimeline = sortedTimeline.filter((event) => event.scoreAvailable !== false);
  const trajectoryAvailable = scoredTimeline.length >= 2;
  const firstScore = scoredTimeline[0]?.score ?? 0;
  const lastScore = scoredTimeline[scoredTimeline.length - 1]?.score ?? 0;
  const trajectoryLabel = lastScore >= firstScore + 0.6 ? "improved under pressure" : lastScore <= firstScore - 0.6 ? "degraded under pressure" : "stayed relatively stable under pressure";
  const readyResponsibilities = responsibilities.filter((item) => item.status === "Ready").length;
  const supportedResponsibilities = responsibilities.filter((item) => item.status === "Supported").length;
  const avoidResponsibilities = responsibilities.filter((item) => item.status === "Avoid").length;
  return (
    <Panel title="Trajectory and responsibility analytics">
      <div className="grid gap-5 xl:grid-cols-[1.15fr_0.85fr]">
        <div className="rounded-lg border border-slate-200 bg-slate-50 p-4">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <p className="font-mono text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-500">Probe pressure trajectory</p>
              <h3 className="mt-2 text-xl font-semibold text-slate-950">
                {trajectoryAvailable
                  ? `The candidate ${trajectoryLabel}.`
                  : "Pressure trajectory was not measured."}
              </h3>
              <p className="mt-2 text-sm leading-6 text-slate-600">
                This line shows how answer quality moved as the interview shifted from opening claims into pressure probes, ownership calibration, and failure-mode questioning.
              </p>
            </div>
            <span className="rounded-md border border-slate-200 bg-white px-3 py-2 font-mono text-xs font-semibold text-slate-700">
              {trajectoryAvailable
                ? `${firstScore.toFixed(1)} to ${lastScore.toFixed(1)}`
                : "Not available"}
            </span>
          </div>
          {scoredTimeline.length ? (
          <div className="mt-5 grid grid-cols-[repeat(auto-fit,minmax(44px,1fr))] items-end gap-2">
            {scoredTimeline.map((event) => (
              <div key={`${event.turn}-${event.route}`} className="grid gap-2">
                <div className="flex h-32 items-end rounded-md border border-slate-200 bg-white p-1">
                  <div className="w-full rounded-sm" style={{ height: `${Math.max(10, event.score * 10)}%`, background: scoreColor(event.score) }} />
                </div>
                <p className="text-center font-mono text-[10px] font-semibold text-slate-600">{event.turn}</p>
              </div>
            ))}
          </div>
          ) : (
            <p className="mt-5 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm leading-6 text-amber-900">
              Per-turn scores were not retained. The report will not substitute
              the overall interview score for every turn.
            </p>
          )}
        </div>

        <div className="grid gap-3">
          <div className="rounded-lg border border-slate-200 bg-white p-4">
            <p className="font-mono text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-500">Responsibility distribution</p>
            {responsibilities.length ? (
              <div className="mt-4 grid gap-3">
                <StackedBar label="Evidence supports" value={readyResponsibilities} total={responsibilities.length} tone="green" />
                <StackedBar label="More evidence needed" value={supportedResponsibilities} total={responsibilities.length} tone="amber" />
                <StackedBar label="Evidence contradicts" value={avoidResponsibilities} total={responsibilities.length} tone="red" />
              </div>
            ) : (
              <p className="mt-4 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm leading-6 text-amber-900">Not assessed. No employer-approved responsibility rubric was attached to this session, so missing responsibilities are not scored as zero.</p>
            )}
          </div>
          <div className="rounded-lg border border-slate-200 bg-white p-4">
            <p className="font-mono text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-500">Evidence balance map</p>
            {heatmap.length ? <div className="mt-3 grid gap-2">
              {heatmap.map((row) => (
                <div key={row.area}>
                  <div className="flex items-center justify-between gap-3">
                    <p className="text-xs font-semibold text-slate-700">{row.area}</p>
                    <p className="font-mono text-[10px] text-slate-500">risk {row.risk.toFixed(1)}</p>
                  </div>
                  <div className="mt-1 grid grid-cols-4 gap-1">
                    {[row.mechanism, row.pressure, row.ownership, 10 - row.risk].map((value, index) => (
                      <span key={`${row.area}-${index}`} className="h-2 rounded-full" style={{ background: scoreColor(value), opacity: 0.35 + value / 16 }} />
                    ))}
                  </div>
                </div>
              ))}
            </div> : (
              <p className="mt-3 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm leading-6 text-amber-900">
                A structured heat map was not emitted. Missing mechanism,
                pressure, ownership, and risk values are not filled from the
                overall score.
              </p>
            )}
          </div>
        </div>
      </div>
    </Panel>
  );
}

function StackedBar({ label, value, total, tone }: { label: string; value: number; total: number; tone: "green" | "amber" | "red" }) {
  const percent = total ? (value / total) * 100 : 0;
  const color = tone === "green" ? "#059669" : tone === "red" ? "#e11d48" : "#d97706";
  return (
    <div>
      <div className="flex items-center justify-between gap-3">
        <p className="text-xs font-semibold text-slate-700">{label}</p>
        <p className="font-mono text-xs font-semibold text-slate-800">{value}/{total}</p>
      </div>
      <div className="mt-2 h-2 overflow-hidden rounded-full bg-slate-200">
        <div className="h-full rounded-full" style={{ width: `${Math.max(3, percent)}%`, background: color }} />
      </div>
    </div>
  );
}

function LensFocusPanel({
  report,
  lens,
  responsibilities,
  heat,
  weakness,
  turn,
}: {
  report: DemoReport;
  lens: Lens;
  responsibilities: ResponsibilityFit[];
  heat: HeatmapRow;
  weakness: WeaknessFinding;
  turn: DemoReport["timeline"][number];
}) {
  if (lens === "responsibilities") {
    if (!responsibilities.length)
      return (
        <Panel title="Responsibility evidence unavailable">
          <div className="rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm leading-7 text-amber-900">
            No employer-approved responsibility rubric was attached to this
            session. The report does not infer work ownership, readiness, or
            assignment safety from generic interview dimensions.
          </div>
        </Panel>
      );
    const ready = responsibilities.filter((item) => item.status === "Ready");
    const guarded = responsibilities.filter((item) => item.status !== "Ready");
    return (
      <Panel title="Responsibility ownership view">
        <div className="grid gap-4 lg:grid-cols-2">
          <SignalCard label="Responsibilities the candidate can likely own with normal onboarding" value={ready.map((item) => item.label).join(", ") || "No responsibility is fully unguarded yet."} tone="green" />
          <SignalCard label="Responsibilities that need senior support, extra probing, or should not be assigned yet" value={guarded.map((item) => item.label).join(", ") || "No major guarded responsibility."} tone={guarded.some((item) => item.status === "Avoid") ? "red" : "amber"} />
        </div>
        <div className="mt-4 grid gap-3 md:grid-cols-2">
          {responsibilities.map((item) => (
            <RubricDetails key={item.label} title={`Responsibility read: ${item.label}`} items={responsibilityRubricFor(item)} />
          ))}
        </div>
      </Panel>
    );
  }

  if (lens === "evidence") {
    const heatAvailable = heat.area !== UNAVAILABLE_HEATMAP.area;
    return (
      <Panel title="Evidence review">
        <div className="grid gap-4 lg:grid-cols-[0.9fr_1.1fr]">
          <SignalCard label="Evidence area currently selected in the heat map" value={heatAvailable ? `${heat.area}: mechanism ${heat.mechanism.toFixed(1)}, ownership ${heat.ownership.toFixed(1)}, residual risk ${heat.risk.toFixed(1)}` : "Not measured. The source report did not emit a structured heat map."} tone="cyan" />
          <SignalCard label="Interview probe currently selected in the timeline" value={`${turn.turn}. ${turn.route}: ${turn.observation}`} tone={turn.scoreAvailable === false ? "cyan" : turn.score >= 7 ? "green" : turn.score >= 5 ? "amber" : "red"} />
        </div>
        <div className="mt-4">
          <RubricDetails
            title="How to interpret this evidence"
            defaultOpen
            items={[
              { label: "What the panel can trust", value: report.strongestSignal, tone: "green" },
              { label: "What is still unresolved", value: report.largestRisk, tone: report.tone === "risk" ? "red" : "amber" },
              { label: "Strong case", value: "A strong case has voluntary mechanism, pressure-tested failure handling, calibrated ownership, and a concrete metric.", tone: "cyan" },
              { label: "Next probe", value: report.recommendedFollowups[0], tone: "slate" },
            ]}
          />
        </div>
      </Panel>
    );
  }

  if (lens === "risks") {
    return (
      <Panel title="Risk review">
        <div className="grid gap-4 lg:grid-cols-2">
          <SignalCard label="Largest unresolved risk that should shape the next evidence check" value={report.largestRisk} tone={report.tone === "risk" ? "red" : "amber"} />
          <SignalCard label="Weakness currently selected for detailed inspection" value={`${weakness.area}: ${weakness.interpretation}`} tone={weakness.severity === "high" ? "red" : "amber"} />
        </div>
        <div className="mt-4 grid gap-3 md:grid-cols-2">
          <RubricDetails title={`Why ${weakness.area} is ${weakness.severity}`} items={weaknessRubricFor(weakness)} defaultOpen />
          <RubricDetails title="Claim calibration standard" items={claimRubricFor(report.claims[0])} />
        </div>
      </Panel>
    );
  }

  if (lens === "next") {
    return (
      <Panel title="Next action plan">
        <div className="grid gap-3 lg:grid-cols-3">
          {report.recommendedFollowups.map((item, index) => (
            <ActionLane key={`${index}-${item}`} index={index} item={item} report={report} />
          ))}
        </div>
        <div className="mt-4">
          <RubricDetails
            title="Panel evidence memo"
            defaultOpen
            items={[
              { label: "Role-fit boundary", value: report.roleFit, tone: "cyan" },
              { label: "Risk that requires additional validation", value: report.largestRisk, tone: report.tone === "risk" ? "red" : "amber" },
              { label: "Strongest supported interview signal", value: report.strongestSignal, tone: "green" },
              { label: "Panel note", value: report.hiringPanelNotes[0], tone: "slate" },
            ]}
          />
        </div>
      </Panel>
    );
  }

  return (
    <Panel title="Interview evidence summary">
      <div className="grid gap-4 lg:grid-cols-3">
        <SignalCard label="Interview evidence state and role-fit limitation" value={`${report.verdict}: ${report.roleFit}`} tone={report.tone === "risk" ? "red" : report.tone === "mixed" ? "amber" : "green"} />
        <SignalCard label="Strongest verified signal the panel can safely cite" value={report.strongestSignal} tone="green" />
        <SignalCard label="Largest unresolved risk the panel should not gloss over" value={report.largestRisk} tone={report.tone === "risk" ? "red" : "amber"} />
      </div>
      <div className="mt-4 grid gap-3 md:grid-cols-2">
        {report.scores.slice(0, 4).map((score) => (
          <RubricDetails key={score.label} title={`Score read: ${score.label}`} items={scoreRubricFor(score)} />
        ))}
      </div>
    </Panel>
  );
}

function ResponsibilityLens({ responsibilities, report }: { responsibilities: ResponsibilityFit[]; report: DemoReport }) {
  return (
    <div className="grid gap-5">
      <Panel title="Responsibility fit matrix">
        {responsibilities.length ? <div className="grid gap-3">
          {responsibilities.map((item) => (
            <div key={item.label} className="grid gap-4 rounded-lg border border-slate-200 bg-white p-4 md:grid-cols-[minmax(0,1fr)_220px] md:items-center">
              <div>
                <div className="flex flex-wrap items-center gap-2">
                  <p className="text-base font-semibold text-slate-950">{item.label}</p>
                  <span className={`rounded-md border px-2 py-1 font-mono text-[10px] uppercase tracking-[0.14em] ${responsibilityClass(item.status)}`}>{item.status}</span>
                </div>
                <p className="mt-2 text-sm leading-6 text-slate-600">{item.detail}</p>
                <div className="mt-3">
                  <RubricDetails title="Why this responsibility rating?" items={responsibilityRubricFor(item)} />
                </div>
              </div>
              <ReadinessBar value={item.score} />
            </div>
          ))}
        </div> : <div className="rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm leading-7 text-amber-900">Role responsibility fit was not assessed because this report has no employer-approved responsibility rubric. Configure the target responsibilities and required evidence before drawing any role-ownership conclusion.</div>}
      </Panel>
      <Panel title="Operating envelope">
        <div className="grid gap-3 md:grid-cols-3">
          <SignalCard label="Work areas where the candidate can be used confidently" value={report.strongestSignal} tone="green" />
          <SignalCard label="Work areas where the manager should add support or validate further" value={report.largestRisk} tone="amber" />
          <SignalCard label="How to interpret the candidate's role fit in plain language" value={`${report.roleFit}. ${report.archetype}.`} tone="cyan" />
        </div>
      </Panel>
    </div>
  );
}

function EvidenceLens({
  report,
  heatmap,
  selectedHeat,
  setSelectedHeat,
  selectedTurn,
  setSelectedTurn,
}: {
  report: DemoReport;
  heatmap: HeatmapRow[];
  selectedHeat: number;
  setSelectedHeat: (index: number) => void;
  selectedTurn: number;
  setSelectedTurn: (index: number) => void;
}) {
  return (
    <div className="grid gap-5">
      <Panel title="Evidence heat map">
        {heatmap.length ? <div className="overflow-x-auto rounded-lg border border-slate-200">
          <div className="min-w-[720px]">
            <div className="grid grid-cols-[1.2fr_repeat(4,0.8fr)] border-b border-slate-200 bg-slate-50">
              {["Area", "Mechanism", "Pressure", "Ownership", "Risk"].map((item) => (
                <div key={item} className="px-3 py-3 font-mono text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-500">{item}</div>
              ))}
            </div>
            {heatmap.map((row, index) => (
              <button
                key={row.area}
                type="button"
                data-testid={`heat-row-${slugify(row.area)}`}
                onClick={() => setSelectedHeat(index)}
                className={`grid w-full grid-cols-[1.2fr_repeat(4,0.8fr)] border-b border-slate-100 text-left last:border-b-0 ${selectedHeat === index ? "bg-slate-50" : "bg-white hover:bg-slate-50"}`}
              >
                <div className="px-3 py-3 text-sm font-semibold text-slate-950">{row.area}</div>
                {[row.mechanism, row.pressure, row.ownership, row.risk].map((value, valueIndex) => (
                  <HeatCell key={`${row.area}-${valueIndex}`} value={value} inverse={valueIndex === 3} />
                ))}
              </button>
            ))}
          </div>
        </div> : (
          <div className="rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm leading-7 text-amber-900">
            No structured heat-map evidence was emitted. The report does not
            manufacture mechanism, pressure, ownership, or risk values from the
            overall interview score.
          </div>
        )}
      </Panel>
      <Panel title="Probe timeline">
        <div className="mb-4 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm leading-6 text-amber-950">
          Transcript text is uncorrected speech recognition evidence. Verify
          technical terms against audio or a candidate-approved correction
          before using wording differences in a hiring decision.
        </div>
        <div className="grid gap-3">
          {report.timeline.map((event, index) => (
            <button
              key={`${event.turn}-${event.route}`}
              type="button"
              onClick={() => setSelectedTurn(index)}
              className={`grid gap-3 rounded-lg border p-4 text-left transition md:grid-cols-[70px_1fr_110px] md:items-center ${
                selectedTurn === index ? "border-slate-950 bg-slate-50" : "border-slate-200 bg-white hover:bg-slate-50"
              }`}
            >
              <div>
                <p className="font-mono text-lg font-semibold text-slate-950">{event.turn}</p>
                <p className="mt-1 font-mono text-[10px] uppercase tracking-[0.14em] text-slate-500">{event.signal}</p>
              </div>
              <div>
                <p className="text-sm font-semibold text-slate-950">{event.route}</p>
                {event.question ? <p className="mt-2 text-xs leading-5 text-slate-800"><strong>Question:</strong> {event.question}</p> : <p className="mt-2 text-xs leading-5 text-amber-700">Question text was not retained; do not judge answer relevance from this row alone.</p>}
                <p className="mt-1 text-xs leading-5 text-slate-600"><strong>Answer/evidence:</strong> {event.observation}</p>
              </div>
              {event.scoreAvailable === false ? (
                <div className="rounded-md border border-slate-200 bg-slate-50 p-3 text-center font-mono text-[10px] uppercase tracking-[0.12em] text-slate-500">
                  Not scored
                </div>
              ) : (
                <ReadinessBar value={event.score * 10} />
              )}
            </button>
          ))}
        </div>
      </Panel>
      <Panel title="Knowledge coverage map">
        <CoverageMap coverage={report.coverage} />
      </Panel>
    </div>
  );
}

function RiskLens({ report, selectedWeakness, setSelectedWeakness }: { report: DemoReport; selectedWeakness: number; setSelectedWeakness: (index: number) => void }) {
  return (
    <div className="grid gap-5">
      <Panel title="Weakness localization">
        <div className="grid gap-3">
          {report.weaknesses.map((weakness, index) => (
            <div
              key={weakness.area}
              data-testid={`weakness-row-${slugify(weakness.area)}`}
              className={`rounded-lg border p-4 text-left transition ${selectedWeakness === index ? "border-slate-950 bg-slate-50" : "border-slate-200 bg-white hover:bg-slate-50"}`}
            >
              <button type="button" onClick={() => setSelectedWeakness(index)} className="w-full text-left">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <p className="text-base font-semibold text-slate-950">{weakness.area}</p>
                  <span className={`rounded-md border px-2 py-1 font-mono text-[10px] uppercase tracking-[0.14em] ${severityClass(weakness.severity)}`}>{weakness.severity}</span>
                </div>
                <p className="mt-3 text-sm leading-6 text-slate-600">{weakness.interpretation}</p>
              </button>
              <div className="mt-3">
                <RubricDetails title="What led to this weakness rating?" items={weaknessRubricFor(weakness)} />
              </div>
            </div>
          ))}
        </div>
      </Panel>
      <Panel title="Claim calibration">
        <div className="space-y-3">
          {report.claims.map((claim) => <ClaimCard key={claim.claim} claim={claim} />)}
        </div>
      </Panel>
    </div>
  );
}

function NextLens({ report }: { report: DemoReport }) {
  return (
    <div className="grid gap-5">
      <Panel title="Evidence follow-up board">
        <div className="grid gap-3 lg:grid-cols-3">
          {report.recommendedFollowups.map((item, index) => (
            <ActionLane key={`${index}-${item}`} index={index} item={item} report={report} />
          ))}
        </div>
      </Panel>
      <div className="grid gap-5 xl:grid-cols-[1fr_0.9fr]">
        <Panel title="Signal ledger">
          <div className="grid gap-3 md:grid-cols-2">
            {report.strengths.map((item, index) => (
              <SignalLedgerRow key={item} label={`Verified strength ${index + 1}`} value={item} tone="green" />
            ))}
            {report.risks.map((item, index) => (
              <SignalLedgerRow key={item} label={`Open risk ${index + 1}`} value={item} tone={report.tone === "risk" ? "red" : "amber"} />
            ))}
          </div>
        </Panel>
        <Panel title="Panel memo">
          <div className="space-y-3">
            {report.hiringPanelNotes.map((item, index) => (
              <PanelMemo key={item} index={index} value={item} report={report} />
            ))}
          </div>
        </Panel>
      </div>
    </div>
  );
}

function ActionLane({ index, item, report }: { index: number; item: string; report: DemoReport }) {
  const labels = ["Follow-up probe", "Evidence check", "Validation condition"];
  const color = index === 0 ? "#0891b2" : index === 1 ? scoreColor(report.score) : report.tone === "risk" ? "#e11d48" : "#d97706";
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
      <div className="flex items-center justify-between gap-3">
        <span className="rounded-md border border-slate-200 bg-slate-50 px-2 py-1 font-mono text-[10px] uppercase tracking-[0.14em] text-slate-500">
          {labels[index] ?? `Step ${index + 1}`}
        </span>
        <span className="h-2.5 w-2.5 rounded-full" style={{ background: color }} />
      </div>
      <p className="mt-4 text-sm font-semibold leading-6 text-slate-950">{item}</p>
      <div className="mt-4 h-1.5 overflow-hidden rounded-full bg-slate-200">
        <div className="h-full rounded-full" style={{ width: `${Math.max(36, 100 - index * 18)}%`, background: color }} />
      </div>
    </div>
  );
}

function SignalLedgerRow({ label, value, tone }: { label: string; value: string; tone: "green" | "amber" | "red" }) {
  const cls =
    tone === "green"
      ? "border-l-emerald-500 bg-emerald-50/50"
      : tone === "red"
        ? "border-l-rose-500 bg-rose-50/50"
        : "border-l-amber-500 bg-amber-50/50";
  return (
    <div className={`rounded-lg border border-l-4 border-slate-200 p-4 ${cls}`}>
      <p className="font-mono text-[10px] font-semibold uppercase tracking-[0.15em] text-slate-500">{label}</p>
      <p className="mt-2 text-sm leading-6 text-slate-800">{value}</p>
    </div>
  );
}

function PanelMemo({ index, value, report }: { index: number; value: string; report: DemoReport }) {
  const decisionColor = report.tone === "risk" ? "#e11d48" : report.tone === "mixed" ? "#d97706" : "#059669";
  return (
    <div className="grid grid-cols-[42px_1fr] gap-3 rounded-lg border border-slate-200 bg-slate-50 p-4">
      <div className="flex h-10 w-10 items-center justify-center rounded-md font-mono text-xs font-semibold text-white" style={{ background: index === 0 ? decisionColor : "#334155" }}>
        {index + 1}
      </div>
      <div>
        <p className="font-mono text-[10px] uppercase tracking-[0.14em] text-slate-500">{index === 0 ? "Primary follow-up" : "Panel context"}</p>
        <p className="mt-1 text-sm leading-6 text-slate-800">{value}</p>
      </div>
    </div>
  );
}

function RecruiterSideRail({
  report,
  lens,
  strongest,
  weakest,
  heat,
  weakness,
  turn,
}: {
  report: DemoReport;
  lens: Lens;
  strongest: DimensionScore;
  weakest: DimensionScore;
  heat: HeatmapRow;
  weakness: WeaknessFinding;
  turn: DemoReport["timeline"][number];
}) {
  const dynamic = sideRailContextFor(report, lens, heat, weakness, turn);
  return (
    <aside className="grid gap-4 lg:grid-cols-2 xl:grid-cols-1 xl:sticky xl:top-5 xl:self-start">
      <section className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
        <p className="font-mono text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500">Fixed candidate context</p>
        <div className="mt-4 grid gap-3">
          <SignalTile label="Role-fit boundary from this interview" value={report.roleFit} detail={`${report.verdict} / claim risk ${report.claimRisk}`} tone={report.tone === "risk" ? "red" : report.tone === "mixed" ? "amber" : "green"} />
          <SignalTile label="Strongest dimension" value={strongest.label} detail={`${strongest.score.toFixed(1)} / ${strongest.note}`} tone="green" />
          <SignalTile label="Lowest-scoring dimension that limits what the candidate should own immediately" value={weakest.label} detail={`${weakest.score.toFixed(1)} / ${weakest.note}`} tone={report.tone === "risk" ? "red" : "amber"} />
        </div>
      </section>

      <section className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="font-mono text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500">Changes with selected report view</p>
          <span className="rounded-md border border-slate-200 bg-slate-50 px-2 py-1 font-mono text-[10px] uppercase tracking-[0.14em] text-slate-500">{lensLabels[lens]}</span>
        </div>
        <h2 className="mt-4 text-2xl font-semibold text-slate-950">{dynamic.value}</h2>
        <p className="mt-1 font-mono text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-500">{dynamic.label}</p>
        <div className="mt-4 space-y-3">
          {dynamic.items.map((item) => (
            <p key={item} className="rounded-lg border border-slate-200 bg-slate-50 p-3 text-sm leading-6 text-slate-700">{item}</p>
          ))}
        </div>
      </section>
    </aside>
  );
}

function sideRailContextFor(report: DemoReport, lens: Lens, heat: HeatmapRow, weakness: WeaknessFinding, turn: DemoReport["timeline"][number]) {
  const content: Record<Lens, { label: string; value: string; items: string[] }> = {
    decision: {
      label: "Evidence anchor",
      value: report.roleFit,
      items: [report.strongestSignal, report.largestRisk, report.executiveRead],
    },
    responsibilities: {
      label: "Responsibility interpretation",
      value: report.archetype,
      items: [`Ready to own: ${report.strongestSignal}`, `Needs support or validation: ${report.largestRisk}`, `Claim risk is ${report.claimRisk}.`],
    },
    evidence: {
      label: "Selected heat read",
      value: heat.area,
      items:
        heat.area === UNAVAILABLE_HEATMAP.area
          ? [
              "The source report did not emit a structured heat map.",
              "Missing values are not filled from the overall interview result.",
              `Selected probe: ${turn.turn} - ${turn.signal}`,
            ]
          : [`Mechanism ${heat.mechanism.toFixed(1)}`, `Pressure ${heat.pressure.toFixed(1)}`, `Ownership ${heat.ownership.toFixed(1)}`, `Risk ${heat.risk.toFixed(1)}`, `Selected probe: ${turn.turn} - ${turn.signal}`],
    },
    risks: {
      label: "Risk localization",
      value: weakness.area,
      items: [weakness.trigger, weakness.interpretation, weakness.followup],
    },
    next: {
      label: "Action package",
      value: report.verdict,
      items: report.recommendedFollowups,
    },
  };
  return content[lens];
}

function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="min-w-0 rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
      <p className="font-mono text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500">{title}</p>
      <div className="mt-4">{children}</div>
    </section>
  );
}

function HeroStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="border-slate-200 px-5 py-4 md:border-r md:last:border-r-0">
      <p className="font-mono text-[10px] uppercase tracking-[0.16em] text-slate-500">{label}</p>
      <p className="mt-2 text-xl font-semibold text-slate-950">{value}</p>
    </div>
  );
}

function ScoreDial({ score, color }: { score: number; color: string }) {
  const radius = 46;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference - (score / 10) * circumference;
  return (
    <div className="flex items-center justify-start lg:justify-end">
      <svg viewBox="0 0 120 120" className="h-36 w-36">
        <circle cx="60" cy="60" r={radius} fill="none" stroke="#e2e8f0" strokeWidth="10" />
        <circle cx="60" cy="60" r={radius} fill="none" stroke={color} strokeWidth="10" strokeDasharray={circumference} strokeDashoffset={offset} strokeLinecap="round" transform="rotate(-90 60 60)" />
        <text x="60" y="58" textAnchor="middle" className="fill-slate-950 text-3xl font-semibold">{score.toFixed(1)}</text>
        <text x="60" y="78" textAnchor="middle" className="fill-slate-500 text-[10px] uppercase">interview</text>
      </svg>
    </div>
  );
}

function ScoreBar({ item, color }: { item: DimensionScore; color: string }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-slate-50 p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-sm font-semibold text-slate-950">{item.label}</p>
          <p className="mt-1 text-xs leading-5 text-slate-600">{item.note}</p>
        </div>
        <p className="font-mono text-sm font-semibold text-slate-800">{item.score.toFixed(1)}</p>
      </div>
      <div className="mt-4 h-2 overflow-hidden rounded-full bg-slate-200">
        <div className="h-full rounded-full" style={{ width: `${item.score * 10}%`, background: item.score >= 8 ? color : scoreColor(item.score) }} />
      </div>
      <div className="mt-3">
        <RubricDetails title="Score rationale" items={scoreRubricFor(item)} />
      </div>
    </div>
  );
}

function SignalCard({ label, value, tone }: { label: string; value: string; tone: "green" | "amber" | "red" | "cyan" }) {
  const cls =
    tone === "green"
      ? "border-emerald-200 bg-emerald-50"
      : tone === "red"
        ? "border-rose-200 bg-rose-50"
        : tone === "cyan"
          ? "border-cyan-200 bg-cyan-50"
          : "border-amber-200 bg-amber-50";
  return (
    <div className={`rounded-lg border p-4 ${cls}`}>
      <p className="font-mono text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-500">{label}</p>
      <p className="mt-2 text-sm leading-7 text-slate-800">{value}</p>
    </div>
  );
}

function SignalTile({ label, value, detail, tone }: { label: string; value: string; detail: string; tone: "green" | "amber" | "red" | "cyan" | "slate" }) {
  const border =
    tone === "green" ? "border-emerald-200 bg-emerald-50" : tone === "red" ? "border-rose-200 bg-rose-50" : tone === "cyan" ? "border-cyan-200 bg-cyan-50" : tone === "amber" ? "border-amber-200 bg-amber-50" : "border-slate-200 bg-white";
  return (
    <div className={`rounded-lg border p-4 shadow-sm ${border}`}>
      <p className="font-mono text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-500">{label}</p>
      <p className="mt-2 text-base font-semibold text-slate-950">{value}</p>
      <p className="mt-1 text-xs leading-5 text-slate-600">{detail}</p>
    </div>
  );
}

function ReadinessBar({ value }: { value: number }) {
  return (
    <div>
      <div className="flex items-center justify-between gap-3">
        <span className="font-mono text-[10px] uppercase tracking-[0.14em] text-slate-500">Readiness</span>
        <span className="font-mono text-xs font-semibold text-slate-800">{Math.round(value)}%</span>
      </div>
      <div className="mt-2 h-2 overflow-hidden rounded-full bg-slate-200">
        <div className="h-full rounded-full" style={{ width: `${Math.max(4, Math.min(100, value))}%`, background: scoreColor(value / 10) }} />
      </div>
    </div>
  );
}

function HeatCell({ value, inverse = false }: { value: number; inverse?: boolean }) {
  const display = value.toFixed(1);
  const score = inverse ? 10 - value : value;
  return (
    <div className="px-3 py-3">
      <div className="flex h-10 items-center justify-center rounded-md font-mono text-xs font-semibold text-slate-950" style={{ background: heatBackground(score) }}>
        {display}
      </div>
    </div>
  );
}

function CoverageMap({ coverage }: { coverage: CoverageItem[] }) {
  const groups = coverage.reduce<Record<CoverageItem["state"], CoverageItem[]>>(
    (acc, item) => {
      acc[item.state].push(item);
      return acc;
    },
    { voluntary: [], recovered: [], missed: [], incorrect: [] },
  );

  return (
    <div className="grid gap-3 lg:grid-cols-4">
      {(Object.keys(groups) as CoverageItem["state"][]).map((state) => (
        <div key={state} className="space-y-2">
          <p className="font-mono text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-500">{state}</p>
          {groups[state].map((item) => (
            <div key={item.label} className={`rounded-lg border p-3 ${coverageClass(state)}`}>
              <p className="text-sm font-semibold">{item.label}</p>
              <p className="mt-2 text-xs leading-5 text-slate-600">{item.detail}</p>
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}

function ClaimCard({ claim }: { claim: ClaimFinding }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm font-semibold text-slate-950">{claim.claim}</p>
        <span className={`rounded-md border px-2 py-1 font-mono text-[10px] uppercase tracking-[0.14em] ${claimStatusClass(claim.status)}`}>
          {claim.status.replace(/_/g, " ")}
        </span>
      </div>
      <p className="mt-3 text-xs leading-6 text-slate-600">{claim.evidence}</p>
      <div className="mt-3">
        <RubricDetails title="How to read this claim" items={claimRubricFor(claim)} />
      </div>
    </div>
  );
}

function RubricDetails({ title, items, defaultOpen = false }: { title: string; items: RubricItem[]; defaultOpen?: boolean }) {
  return (
    <details open={defaultOpen} className="rounded-lg border border-slate-200 bg-white p-3">
      <summary className="cursor-pointer list-none text-sm font-semibold text-slate-950">
        <span className="inline-flex w-full items-center justify-between gap-3">
          {title}
          <span className="font-mono text-[10px] uppercase tracking-[0.14em] text-slate-400">Open</span>
        </span>
      </summary>
      <div className="mt-3 grid gap-2 md:grid-cols-2">
        {items.map((item) => (
          <div key={`${item.label}-${item.value}`} className={`rounded-md border p-3 ${detailSurface(item.tone)}`}>
            <p className="font-mono text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-500">{item.label}</p>
            <p className="mt-2 text-xs leading-5 text-slate-700">{item.value}</p>
          </div>
        ))}
      </div>
    </details>
  );
}

function scoreRubricFor(item: DimensionScore): RubricItem[] {
  return [
    { label: "Why this score", value: item.note, tone: item.score >= 8 ? "green" : item.score >= 6 ? "cyan" : item.score >= 4.5 ? "amber" : "red" },
    {
      label: "What was missing",
      value: item.score >= 8 ? "Only edge-case breadth or stakeholder translation remains." : item.score >= 6 ? "Evidence was credible but not consistently voluntary under pressure." : "The answer missed mechanism, proof, or ownership boundaries in role-critical areas.",
      tone: item.score >= 8 ? "cyan" : item.score >= 6 ? "amber" : "red",
    },
    {
      label: "Strong case",
      value: "A strong case would show voluntary mechanism, concrete metric, failure-mode handling, and calibrated personal ownership.",
      tone: "green",
    },
    {
      label: "Panel implication",
      value: item.score >= 8 ? "Treat as a verified signal." : item.score >= 6 ? "Use as conditional signal and probe once more." : "Do not rely on this area without a follow-up work sample or direct probe.",
      tone: item.score >= 8 ? "green" : item.score >= 6 ? "amber" : "red",
    },
  ];
}

function responsibilityRubricFor(item: ResponsibilityFit): RubricItem[] {
  return [
    { label: "Why", value: item.detail, tone: item.status === "Ready" ? "green" : item.status === "Supported" ? "amber" : "red" },
    {
      label: "Strong case",
      value: "Ready means the candidate can own the responsibility with normal team context, explain failure modes, and identify when to escalate.",
      tone: "green",
    },
    {
      label: "Current support boundary",
      value: item.status === "Ready" ? "No extra support beyond normal onboarding." : item.status === "Supported" ? "Pair with a senior owner until the weak mechanism is validated." : "Do not assign this responsibility without rebuilding the underlying skill.",
      tone: item.status === "Ready" ? "green" : item.status === "Supported" ? "amber" : "red",
    },
    {
      label: "Next evidence",
      value: "Ask for a concrete story with decision, implementation detail, metric, failure case, and ownership boundary.",
      tone: "cyan",
    },
  ];
}

function weaknessRubricFor(weakness: WeaknessFinding): RubricItem[] {
  return [
    { label: "Trigger", value: weakness.trigger, tone: weakness.severity === "high" ? "red" : "amber" },
    { label: "Why it matters", value: weakness.interpretation, tone: weakness.severity === "high" ? "red" : "amber" },
    {
      label: "Strong case",
      value: "A strong answer would name the mechanism, boundary condition, operational signal, and what the candidate personally did or would do first.",
      tone: "green",
    },
    { label: "Follow-up", value: weakness.followup, tone: "cyan" },
  ];
}

function claimRubricFor(claim: ClaimFinding): RubricItem[] {
  return [
    { label: "Why this status", value: claim.evidence, tone: claim.status === "substantiated" ? "green" : claim.status === "partial" ? "amber" : "red" },
    {
      label: "Strong proof",
      value: "Strong proof includes personal scope, mechanism, metric, adjacent owner, and a pressure-tested failure case.",
      tone: "green",
    },
    {
      label: "Risk",
      value: claim.status === "substantiated" ? "Low claim risk; preserve this as a lead evidence story." : claim.status === "partial" ? "Medium claim risk; narrow the claim before relying on it." : "High claim risk; treat as unproven until a work sample or direct mechanism probe supports it.",
      tone: claim.status === "substantiated" ? "green" : claim.status === "partial" ? "amber" : "red",
    },
    {
      label: "Next check",
      value: "Ask the candidate to replay the exact decision they owned, what evidence they saw, and what changed because of it.",
      tone: "cyan",
    },
  ];
}

function scoreColor(score: number) {
  if (score >= 8) return "#059669";
  if (score >= 6) return "#0891b2";
  if (score >= 4.5) return "#d97706";
  return "#e11d48";
}

function heatBackground(score: number) {
  if (score >= 8) return "#d1fae5";
  if (score >= 6) return "#cffafe";
  if (score >= 4.5) return "#fef3c7";
  return "#ffe4e6";
}

function detailSurface(tone: RubricItem["tone"]) {
  if (tone === "green") return "border-emerald-200 bg-emerald-50";
  if (tone === "red") return "border-rose-200 bg-rose-50";
  if (tone === "cyan") return "border-cyan-200 bg-cyan-50";
  if (tone === "amber") return "border-amber-200 bg-amber-50";
  return "border-slate-200 bg-slate-50";
}

function coverageClass(state: CoverageItem["state"]) {
  if (state === "voluntary") return "border-emerald-200 bg-emerald-50 text-emerald-950";
  if (state === "recovered") return "border-amber-200 bg-amber-50 text-amber-950";
  if (state === "incorrect") return "border-rose-200 bg-rose-50 text-rose-950";
  return "border-slate-200 bg-slate-50 text-slate-800";
}

function claimStatusClass(status: ClaimFinding["status"]) {
  if (status === "substantiated") return "border-emerald-200 bg-emerald-50 text-emerald-800";
  if (status === "partial") return "border-amber-200 bg-amber-50 text-amber-800";
  if (status === "not_substantiated") return "border-rose-200 bg-rose-50 text-rose-800";
  return "border-slate-200 bg-slate-50 text-slate-600";
}

function severityClass(severity: WeaknessFinding["severity"]) {
  if (severity === "high") return "border-rose-200 bg-rose-50 text-rose-800";
  if (severity === "medium") return "border-amber-200 bg-amber-50 text-amber-800";
  return "border-cyan-200 bg-cyan-50 text-cyan-800";
}

function responsibilityClass(status: ResponsibilityFit["status"]) {
  if (status === "Ready") return "border-emerald-200 bg-emerald-50 text-emerald-800";
  if (status === "Supported") return "border-amber-200 bg-amber-50 text-amber-800";
  return "border-rose-200 bg-rose-50 text-rose-800";
}

function responsibilityFitFor(report: DemoReport): ResponsibilityFit[] {
  const matrix: Record<string, ResponsibilityFit[]> = {
    "riya-menon-strong": [
      { label: "Own realtime backend reliability", score: 94, status: "Ready", detail: "Can own event delivery semantics, backpressure, rollout safety, and observability." },
      { label: "Lead incident follow-through", score: 91, status: "Ready", detail: "Strong invariant thinking and practical mitigation sequence." },
      { label: "Mentor backend engineers", score: 87, status: "Ready", detail: "Communicates dense systems reasoning well enough to coach others." },
      { label: "Own product-cost prioritization alone", score: 68, status: "Supported", detail: "Needs PM/EM framing when reliability choices become commercial tradeoffs." },
    ],
    "isha-kapoor-fresh": [
      { label: "Implement scoped APIs", score: 76, status: "Ready", detail: "Good junior-level request lifecycle and data access fundamentals." },
      { label: "Write validation and tests", score: 78, status: "Ready", detail: "Naturally thinks about happy path plus failure path." },
      { label: "Participate in on-call shadowing", score: 58, status: "Supported", detail: "Can learn incident rhythm with supervision and explicit runbooks." },
      { label: "Own production reliability independently", score: 34, status: "Avoid", detail: "No tested evidence of operating a service under real pressure." },
    ],
    "nikhil-verma-weak": [
      { label: "Own payment correctness paths", score: 18, status: "Avoid", detail: "Role-critical idempotency and reconciliation claims were not substantiated." },
      { label: "Lead incident response", score: 24, status: "Avoid", detail: "Did not define freeze, audit, customer impact, or recovery order." },
      { label: "Contribute to non-critical backend tasks", score: 42, status: "Supported", detail: "May help with low-risk implementation after hands-on validation." },
      { label: "Communicate high-level architecture", score: 52, status: "Supported", detail: "Surface fluency exists, but must not be confused with ownership." },
    ],
    "meera-rao-mixed": [
      { label: "Own customer-facing feature workflows", score: 78, status: "Ready", detail: "Strongest signal is product-aware dashboard and API execution." },
      { label: "Integrate APIs in defined systems", score: 67, status: "Ready", detail: "Credible detail on auth, pagination, and UI/API interaction." },
      { label: "Debug ambiguous production failures", score: 54, status: "Supported", detail: "Can recover with hints but needs stronger first-principles sequencing." },
      { label: "Own platform data correctness", score: 39, status: "Avoid", detail: "Concurrency and source-of-truth boundaries were not strong enough." },
    ],
  };
  return matrix[report.slug] ?? [];
}

function heatmapFor(report: DemoReport): HeatmapRow[] {
  const demoSlugs = new Set([
    "riya-menon-strong",
    "isha-kapoor-fresh",
    "nikhil-verma-weak",
    "meera-rao-mixed",
  ]);
  if (!demoSlugs.has(report.slug)) return [];
  const getRadar = (label: string) => report.radar.find((item) => item.label === label)?.score ?? report.score;
  const getScore = (label: string) => report.scores.find((item) => item.label === label)?.score ?? report.score;
  return [
    { area: "Core role work", mechanism: getScore("Technical depth"), pressure: getRadar("Failure modes"), ownership: getRadar("Ownership"), risk: 10 - Math.min(9.6, report.score) },
    { area: "Production operations", mechanism: getScore("Production awareness"), pressure: getRadar("Recovery"), ownership: getRadar("Ownership"), risk: 10 - getScore("Production awareness") },
    { area: "Resume claims", mechanism: getScore("Claim integrity"), pressure: getRadar("Mechanism"), ownership: getRadar("Ownership"), risk: report.claimRisk === "high" ? 8.8 : report.claimRisk === "medium" ? 5.6 : 2.2 },
    { area: "Cross-functional fit", mechanism: getRadar("Product judgment"), pressure: getScore("Communication"), ownership: getRadar("Ownership"), risk: 10 - getRadar("Product judgment") },
  ];
}

function slugify(value: string) {
  return value.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/(^-|-$)/g, "");
}
