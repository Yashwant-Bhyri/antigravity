"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import type { DemoReport, ReportTone } from "./report-data";

type ViewMode = "admin" | "candidate";
type ToneFilter = "all" | ReportTone;

const toneLabel: Record<ReportTone, string> = {
  elite: "Strong",
  emerging: "Fresh",
  risk: "Weak",
  mixed: "Mixed",
};

const toneClass: Record<ReportTone, string> = {
  elite: "border-emerald-200 bg-emerald-50 text-emerald-800",
  emerging: "border-cyan-200 bg-cyan-50 text-cyan-800",
  risk: "border-rose-200 bg-rose-50 text-rose-800",
  mixed: "border-amber-200 bg-amber-50 text-amber-800",
};

const scoreColor = (score: number) => {
  if (score >= 8) return "#059669";
  if (score >= 6) return "#0891b2";
  if (score >= 4.5) return "#d97706";
  return "#e11d48";
};

export function ReportGallery({ reports }: { reports: DemoReport[] }) {
  const [mode, setMode] = useState<ViewMode>("admin");
  const [filter, setFilter] = useState<ToneFilter>("all");
  const [activeSlug, setActiveSlug] = useState(reports[0]?.slug ?? "");

  const visibleReports = useMemo(
    () => reports.filter((report) => filter === "all" || report.tone === filter),
    [filter, reports],
  );
  const activeReport = visibleReports.find((report) => report.slug === activeSlug) ?? visibleReports[0] ?? reports[0];
  const averageScore = reports.reduce((sum, report) => sum + report.score, 0) / Math.max(1, reports.length);
  const strongCount = reports.filter((report) => report.tone === "elite" || report.tone === "emerging").length;
  const riskCount = reports.filter((report) => report.tone === "risk").length;

  return (
    <main className="min-h-screen bg-[linear-gradient(180deg,#f7faf9_0%,#eef4f6_45%,#f9fafb_100%)] px-4 py-5 text-slate-950 md:px-8">
      <div className="mx-auto grid max-w-[1500px] gap-5 xl:grid-cols-[320px_1fr]">
        <aside className="xl:sticky xl:top-5 xl:self-start">
          <section className="overflow-hidden rounded-lg border border-slate-200 bg-white shadow-sm">
            <div className="border-b border-slate-200 bg-[#101820] p-5 text-white">
              <p className="font-mono text-[11px] font-semibold uppercase tracking-[0.18em] text-cyan-200">Antigravity reports</p>
              <h1 className="mt-3 text-3xl font-semibold">Interview report command center</h1>
              <p className="mt-3 text-sm leading-6 text-slate-300">
                Admin and candidate views for the same four fictional assessments, with separate report paths and decision surfaces.
              </p>
            </div>
            <div className="grid grid-cols-2 gap-3 p-4">
              <Metric label="Reports" value={String(reports.length)} />
              <Metric label="Avg score" value={averageScore.toFixed(1)} />
              <Metric label="Advanceable" value={String(strongCount)} />
              <Metric label="High risk" value={String(riskCount)} />
            </div>
          </section>

          <section className="mt-4 rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
            <p className="font-mono text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500">Report view</p>
            <div className="mt-3 grid gap-2">
              {[
                ["admin", "Admin", "Candidate pipeline, risk triage, report handoff"],
                ["candidate", "Candidate", "Select your report and open reflection view"],
              ].map(([value, label, detail]) => (
                <button
                  key={value}
                  type="button"
                  data-testid={`gallery-mode-${value}`}
                  onClick={() => setMode(value as ViewMode)}
                  className={`rounded-lg border px-3 py-3 text-left transition ${
                    mode === value ? "border-slate-950 bg-slate-950 text-white shadow-sm" : "border-slate-200 bg-slate-50 text-slate-700 hover:border-slate-300 hover:bg-white"
                  }`}
                >
                  <span className="block text-sm font-semibold">{label}</span>
                  <span className={`mt-1 block text-xs leading-5 ${mode === value ? "text-slate-300" : "text-slate-500"}`}>{detail}</span>
                </button>
              ))}
            </div>
          </section>
        </aside>

        <div className="min-w-0 space-y-5">
          <section className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm md:p-5">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <p className="font-mono text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500">
                  {mode === "admin" ? "Admin review queue" : "Candidate report selector"}
                </p>
                <p className="mt-1 text-xl font-semibold text-slate-950">
                  {mode === "admin" ? "Compare candidates, inspect risk, then open the admin report." : "Choose a candidate and open the candidate-facing reflection report."}
                </p>
              </div>
              <div className="flex flex-wrap gap-2">
                {(["all", "elite", "emerging", "mixed", "risk"] as ToneFilter[]).map((item) => (
                  <button
                    key={item}
                    type="button"
                    data-testid={`gallery-filter-${item}`}
                    onClick={() => setFilter(item)}
                    className={`rounded-md border px-3 py-2 font-mono text-[10px] font-semibold uppercase tracking-[0.14em] transition ${
                      filter === item ? "border-slate-950 bg-slate-950 text-white" : "border-slate-200 bg-white text-slate-600 hover:border-slate-400"
                    }`}
                  >
                    {item === "all" ? "All" : toneLabel[item]}
                  </button>
                ))}
              </div>
            </div>
          </section>

          {mode === "admin" ? (
            <AdminWorkspace reports={visibleReports} activeReport={activeReport} onSelect={setActiveSlug} />
          ) : (
            <CandidateSelector reports={visibleReports} activeReport={activeReport} onSelect={setActiveSlug} />
          )}
        </div>
      </div>
    </main>
  );
}

function AdminWorkspace({ reports, activeReport, onSelect }: { reports: DemoReport[]; activeReport: DemoReport; onSelect: (slug: string) => void }) {
  return (
    <section className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_380px]">
      <div className="rounded-lg border border-slate-200 bg-white shadow-sm">
        <div className="grid grid-cols-[1.2fr_0.7fr_0.7fr_0.7fr_120px] gap-3 border-b border-slate-200 bg-slate-50 px-4 py-3 font-mono text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-500 max-lg:hidden">
          <span>Candidate</span>
          <span>Decision</span>
          <span>Score</span>
          <span>Risk</span>
          <span>Report</span>
        </div>
        <div className="divide-y divide-slate-100">
          {reports.map((report) => (
            <div
              key={report.slug}
              className={`grid gap-3 px-4 py-4 transition lg:grid-cols-[minmax(0,1.2fr)_0.7fr_0.7fr_0.7fr_120px] lg:items-center ${
                activeReport.slug === report.slug ? "bg-cyan-50/70" : "bg-white hover:bg-slate-50"
              }`}
            >
              <button
                type="button"
                onClick={() => onSelect(report.slug)}
                className="grid w-full gap-3 text-left lg:col-span-4 lg:grid-cols-[minmax(0,1.2fr)_0.7fr_0.7fr_0.7fr] lg:items-center"
              >
                <span>
                  <span className="block text-base font-semibold text-slate-950">{report.candidate}</span>
                  <span className="mt-1 block text-xs text-slate-500">{report.targetRole}</span>
                </span>
                <span className={`w-fit rounded-md border px-2.5 py-1 font-mono text-[10px] font-semibold uppercase tracking-[0.14em] ${toneClass[report.tone]}`}>
                  {report.verdict}
                </span>
                <span className="grid gap-1">
                  <span className="font-mono text-sm font-semibold text-slate-900">{report.score.toFixed(1)}/10</span>
                  <span className="h-1.5 overflow-hidden rounded-full bg-slate-200">
                    <span className="block h-full rounded-full" style={{ width: `${report.score * 10}%`, background: scoreColor(report.score) }} />
                  </span>
                </span>
                <span className="text-sm font-semibold capitalize text-slate-700">{report.claimRisk}</span>
              </button>
              <Link
                href={`/demo-reports/${report.slug}`}
                className="w-fit rounded-md border border-slate-950 bg-slate-950 px-3 py-2 text-xs font-semibold text-white visited:text-white hover:bg-slate-800 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-slate-950"
                style={{ color: "#ffffff" }}
              >
                View report
              </Link>
            </div>
          ))}
        </div>
      </div>
      <AdminSpotlight report={activeReport} />
    </section>
  );
}

function CandidateSelector({ reports, activeReport, onSelect }: { reports: DemoReport[]; activeReport: DemoReport; onSelect: (slug: string) => void }) {
  return (
    <section className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_390px]">
      <div className="grid gap-3 md:grid-cols-2">
        {reports.map((report) => (
          <CandidateCard key={report.slug} report={report} active={report.slug === activeReport.slug} onSelect={() => onSelect(report.slug)} />
        ))}
      </div>
      <CandidateSpotlight report={activeReport} />
    </section>
  );
}

function CandidateCard({ report, active, onSelect }: { report: DemoReport; active: boolean; onSelect: () => void }) {
  return (
    <button
      type="button"
      onClick={onSelect}
      className={`group rounded-lg border bg-white p-4 text-left shadow-sm transition hover:-translate-y-0.5 hover:shadow-md ${
        active ? "border-slate-950 ring-2 ring-slate-950/10" : "border-slate-200"
      }`}
    >
      <div className="grid gap-4">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className={`rounded-md border px-2.5 py-1 font-mono text-[10px] font-semibold uppercase tracking-[0.14em] ${toneClass[report.tone]}`}>
              {report.verdict}
            </span>
            <span className="rounded-md border border-slate-200 bg-slate-50 px-2.5 py-1 font-mono text-[10px] uppercase tracking-[0.14em] text-slate-500">
              {report.experience}
            </span>
          </div>
          <p className="mt-3 text-2xl font-semibold text-slate-950">{report.candidate}</p>
          <p className="mt-1 text-sm text-slate-600">{report.targetRole}</p>
          <p className="mt-3 max-w-3xl text-sm leading-6 text-slate-700">{report.headline}</p>
        </div>
        <div className="grid gap-2 sm:grid-cols-3">
          <MiniMeter label="Score" value={report.score * 10} display={report.score.toFixed(1)} />
          <MiniMeter label="Coverage" value={report.coverageScore * 100} display={`${Math.round(report.coverageScore * 100)}%`} />
          <MiniMeter label="Confidence" value={report.confidence * 100} display={`${Math.round(report.confidence * 100)}%`} />
        </div>
      </div>
    </button>
  );
}

function AdminSpotlight({ report }: { report: DemoReport }) {
  return (
    <aside className="lg:sticky lg:top-5 lg:self-start">
      <section className="overflow-hidden rounded-lg border border-slate-200 bg-white shadow-sm">
        <div className="border-b border-slate-200 bg-[#f8fbfb] p-5">
          <p className="font-mono text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500">Admin preview</p>
          <h2 className="mt-3 text-3xl font-semibold text-slate-950">{report.candidate}</h2>
          <p className="mt-2 text-sm leading-6 text-slate-600">{report.archetype}</p>
        </div>
        <div className="space-y-4 p-5">
          <ScoreBand label="Decision strength" value={report.score * 10} />
          <Insight label="Strongest verified signal" value={report.strongestSignal} tone="green" />
          <Insight label="Risk to inspect" value={report.largestRisk} tone={report.tone === "risk" ? "red" : "amber"} />
          <div className="grid grid-cols-2 gap-3">
            <Metric label="Questions" value={String(report.questions)} />
            <Metric label="Duration" value={report.duration} />
          </div>
          <div className="grid gap-2">
            <Link
              href={`/demo-reports/${report.slug}`}
              className="rounded-md border border-slate-950 bg-slate-950 px-4 py-3 text-center text-sm font-semibold text-white visited:text-white hover:bg-slate-800"
              style={{ color: "#ffffff" }}
            >
              View admin report
            </Link>
            <Link
              href={`/demo-reports/${report.slug}/candidate`}
              className="rounded-md border border-slate-200 bg-white px-4 py-3 text-center text-sm font-semibold text-slate-700 hover:border-slate-400"
            >
              Open candidate-side report
            </Link>
          </div>
        </div>
      </section>
    </aside>
  );
}

function CandidateSpotlight({ report }: { report: DemoReport }) {
  return (
    <aside className="lg:sticky lg:top-5 lg:self-start">
      <section className="overflow-hidden rounded-lg border border-slate-200 bg-white shadow-sm">
        <div className="border-b border-slate-200 bg-[#f8fbfb] p-5">
          <p className="font-mono text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500">Selected candidate</p>
          <h2 className="mt-3 text-3xl font-semibold text-slate-950">{report.candidate}</h2>
          <p className="mt-2 text-sm leading-6 text-slate-600">{report.targetRole}</p>
        </div>
        <div className="space-y-4 p-5">
          <ScoreBand label="Role readiness" value={(report.score * 0.45 + report.coverageScore * 10 * 0.25 + report.interviewQuality * 10 * 0.3) * 10} />
          <Insight label="What to lead with" value={report.strengths[0]} tone="green" />
          <Insight label="First improvement edge" value={report.risks[0]} tone={report.tone === "risk" ? "red" : "amber"} />
          <Link
            href={`/demo-reports/${report.slug}/candidate`}
            className="block rounded-md border border-slate-950 bg-slate-950 px-4 py-3 text-center text-sm font-semibold text-white visited:text-white hover:bg-slate-800"
            style={{ color: "#ffffff" }}
          >
            View candidate report
          </Link>
        </div>
      </section>
    </aside>
  );
}

function MiniMeter({ label, value, display }: { label: string; value: number; display: string }) {
  return (
    <div className="min-w-0 rounded-md border border-slate-200 bg-slate-50 p-3">
      <div className="flex items-center justify-between gap-2">
        <p className="min-w-0 truncate font-mono text-[10px] uppercase tracking-[0.14em] text-slate-500">{label}</p>
        <p className="font-mono text-xs font-semibold text-slate-950">{display}</p>
      </div>
      <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-slate-200">
        <div className="h-full rounded-full" style={{ width: `${Math.max(4, Math.min(100, value))}%`, background: scoreColor(value / 10) }} />
      </div>
    </div>
  );
}

function ScoreBand({ label, value }: { label: string; value: number }) {
  return (
    <div>
      <div className="flex items-center justify-between gap-3">
        <p className="font-mono text-[10px] uppercase tracking-[0.16em] text-slate-500">{label}</p>
        <p className="font-mono text-sm font-semibold text-slate-950">{Math.round(value)}%</p>
      </div>
      <div className="mt-2 h-3 overflow-hidden rounded-full bg-slate-200">
        <div className="h-full rounded-full" style={{ width: `${value}%`, background: scoreColor(value / 10) }} />
      </div>
    </div>
  );
}

function Insight({ label, value, tone }: { label: string; value: string; tone: "green" | "amber" | "red" }) {
  const cls =
    tone === "green"
      ? "border-emerald-200 bg-emerald-50"
      : tone === "red"
        ? "border-rose-200 bg-rose-50"
        : "border-amber-200 bg-amber-50";
  return (
    <div className={`rounded-lg border p-4 ${cls}`}>
      <p className="font-mono text-[10px] uppercase tracking-[0.16em] text-slate-500">{label}</p>
      <p className="mt-2 text-sm leading-6 text-slate-800">{value}</p>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-slate-200 bg-slate-50 p-3">
      <p className="font-mono text-[10px] uppercase tracking-[0.14em] text-slate-500">{label}</p>
      <p className="mt-1 text-lg font-semibold text-slate-950">{value}</p>
    </div>
  );
}
