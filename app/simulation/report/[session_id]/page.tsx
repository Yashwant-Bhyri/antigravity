"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { AGButton, AGChip, AGLogo, AGSectionLabel, AGSurface } from "@/components/design-system";
import { getApiBaseUrl } from "@/lib/api";

type TestDetail = { name: string; status: "pass" | "fail"; visibility?: "public" | "hidden" };
type SimReport = {
  session_id: string;
  scenario: { title: string; role_signal: string };
  report: {
    title: string;
    summary: string;
    overall_score: number;
    breakdown: Record<string, number>;
    hiring_signal: string;
    hiring_label: string;
    reasoning_signal?: {
      label: string;
      status: string;
      quality: number;
      shallow: boolean;
      summary: string;
    };
    overclaim_detected: boolean;
    twist_was_injected: boolean;
    what_proved: string[];
    what_not_proved: string[];
    key_quotes: string[];
    event_timeline: Array<{ ts: string; text: string }>;
    test_result: {
      passed: number; total: number; hidden_passed?: number; hidden_total?: number;
      details: TestDetail[]; runtime_ms: number;
    };
  } | null;
};

function metricLabel(key: string) {
  return key.split("_").map((p) => p.charAt(0).toUpperCase() + p.slice(1)).join(" ");
}

function statusPalette(status: "pass" | "fail") {
  return status === "pass"
    ? "border-[oklch(0.76_0.16_155_/_0.28)] bg-[oklch(0.76_0.16_155_/_0.08)] text-[var(--ag-green)]"
    : "border-[oklch(0.66_0.21_24_/_0.28)] bg-[oklch(0.66_0.21_24_/_0.08)] text-[var(--ag-red)]";
}

export default function SimulationReportPage() {
  const params = useParams<{ session_id: string }>();
  const [data, setData] = useState<SimReport | null>(null);
  const [error, setError] = useState("");
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!params.session_id) return;
    fetch(`${getApiBaseUrl()}/simulation/report/${params.session_id}`)
      .then((r) => r.json())
      .then((payload) => {
        if (payload.detail) throw new Error(payload.detail);
        setData(payload);
      })
      .catch((e) => setError(String(e)));
  }, [params.session_id]);

  function copyLink() {
    navigator.clipboard.writeText(window.location.href).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  }

  if (error) {
    return (
      <main className="ag-shell min-h-screen px-4 py-8 text-[var(--ag-text-0)]">
        <div className="mx-auto max-w-2xl">
          <AGLogo />
          <p className="mt-8 text-[var(--ag-red)]">{error}</p>
          <AGButton variant="secondary" href="/simulation" className="mt-4">Start New Simulation</AGButton>
        </div>
      </main>
    );
  }

  if (!data) {
    return (
      <main className="ag-shell min-h-screen px-4 py-8 text-[var(--ag-text-0)]">
        <div className="mx-auto flex max-w-2xl flex-col items-center gap-4 py-24">
          <AGLogo />
          <p className="text-sm text-[var(--ag-text-3)]">Loading report…</p>
        </div>
      </main>
    );
  }

  const report = data.report;
  if (!report) {
    return (
      <main className="ag-shell min-h-screen px-4 py-8 text-[var(--ag-text-0)]">
        <div className="mx-auto max-w-2xl">
          <AGLogo />
          <p className="mt-8 text-[var(--ag-text-2)]">This simulation has not been finalized yet.</p>
          <AGButton variant="secondary" href="/simulation" className="mt-4">Back to Simulation</AGButton>
        </div>
      </main>
    );
  }

  const hiringColor =
    report.hiring_signal === "strong_hire"
      ? "border-[oklch(0.76_0.16_155_/_0.35)] bg-[oklch(0.76_0.16_155_/_0.12)] text-[var(--ag-green)]"
      : report.hiring_signal === "hire_with_followup"
      ? "border-[oklch(0.8_0.15_200_/_0.3)] bg-[oklch(0.8_0.15_200_/_0.08)] text-[oklch(0.75_0.15_200)]"
      : report.hiring_signal === "no_hire" || report.hiring_signal === "weak"
      ? "border-[oklch(0.66_0.21_24_/_0.3)] bg-[oklch(0.66_0.21_24_/_0.08)] text-[var(--ag-red)]"
      : "border-[var(--ag-border)] bg-[var(--ag-surface-0)] text-[var(--ag-text-2)]";

  return (
    <main className="ag-shell min-h-screen px-4 py-6 text-[var(--ag-text-0)] md:px-8">
      <div className="mx-auto max-w-[1100px]">
        <header className="flex flex-wrap items-center justify-between gap-4">
          <AGLogo />
          <div className="flex flex-wrap items-center gap-2">
            <AGChip active>Assessment Report</AGChip>
            <AGChip>{data.scenario.title}</AGChip>
            <AGButton variant="secondary" onClick={copyLink}>
              {copied ? "Copied!" : "📎 Copy Link"}
            </AGButton>
            <AGButton variant="secondary" href="/simulation">New Simulation</AGButton>
          </div>
        </header>

        <div className="mt-6 grid gap-4 lg:grid-cols-[340px_1fr]">
          <div className="flex flex-col gap-4">
            <AGSurface className="px-5 py-5">
              <AGSectionLabel>Hiring Signal</AGSectionLabel>
              <div className={`mt-3 inline-block rounded-lg border px-3 py-1.5 text-sm font-semibold ${hiringColor}`}>
                {report.hiring_label}
              </div>
              {report.overclaim_detected && (
                <p className="mt-2 text-xs text-[oklch(0.75_0.18_40)]">⚠ Overclaiming detected in candidate notes.</p>
              )}
              <div className="mt-4 flex items-end gap-3">
                <p className="font-mono text-6xl font-semibold tracking-[-0.07em]">{report.overall_score}</p>
                <p className="pb-2 text-sm text-[var(--ag-text-3)]">/ 100</p>
              </div>
              <p className="mt-3 text-sm leading-7 text-[var(--ag-text-2)]">{report.summary}</p>
              {report.twist_was_injected && (
                <p className="mt-3 text-[10px] text-[oklch(0.75_0.18_40)]">↳ Production twist was injected during this session.</p>
              )}
            </AGSurface>

            {report.reasoning_signal && (
              <AGSurface className="px-5 py-5">
                <AGSectionLabel>Reasoning Quality / Authorship Signal</AGSectionLabel>
                <div className={`mt-3 rounded-xl border px-4 py-3 ${
                  report.reasoning_signal.shallow
                    ? "border-[oklch(0.75_0.18_40_/_0.32)] bg-[oklch(0.75_0.18_40_/_0.08)]"
                    : "border-[oklch(0.76_0.16_155_/_0.28)] bg-[oklch(0.76_0.16_155_/_0.07)]"
                }`}>
                  <div className="flex items-center justify-between gap-3">
                    <p className="text-sm font-semibold text-[var(--ag-text-0)]">{report.reasoning_signal.status}</p>
                    <span className="font-mono text-xs text-[var(--ag-text-2)]">{report.reasoning_signal.quality}/100</span>
                  </div>
                  <p className="mt-2 text-xs leading-5 text-[var(--ag-text-2)]">{report.reasoning_signal.summary}</p>
                </div>
              </AGSurface>
            )}

            <AGSurface className="px-5 py-5">
              <AGSectionLabel>Score Breakdown</AGSectionLabel>
              <div className="mt-4 space-y-3">
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
            </AGSurface>

            <AGSurface className="px-5 py-5">
              <AGSectionLabel>Test Evidence</AGSectionLabel>
              <div className="mt-3 grid grid-cols-2 gap-2 text-xs">
                <div className="rounded-xl border border-[var(--ag-border)] bg-[var(--ag-surface-0)] px-3 py-2">
                  <p className="font-mono uppercase text-[var(--ag-text-3)]">Public</p>
                  <p className="mt-1 text-base font-semibold">
                    {report.test_result.passed}/{report.test_result.total}
                  </p>
                </div>
                <div className="rounded-xl border border-[var(--ag-border)] bg-[var(--ag-surface-0)] px-3 py-2">
                  <p className="font-mono uppercase text-[var(--ag-text-3)]">Hidden</p>
                  <p className="mt-1 text-base font-semibold">
                    {report.test_result.hidden_passed ?? 0}/{report.test_result.hidden_total ?? 0}
                  </p>
                </div>
              </div>
              <p className="mt-2 text-[10px] text-[var(--ag-text-3)]">{report.test_result.runtime_ms}ms runtime</p>
            </AGSurface>

            {report.event_timeline?.length > 0 && (
              <AGSurface className="px-5 py-5">
                <AGSectionLabel>Session Timeline</AGSectionLabel>
                <div className="mt-3 space-y-2">
                  {report.event_timeline.map((entry, i) => (
                    <div key={i} className="flex gap-3 border-l border-[var(--ag-border)] pl-3">
                      <span className="shrink-0 font-mono text-[10px] text-[var(--ag-text-3)]">{entry.ts}</span>
                      <span className="text-xs leading-5 text-[var(--ag-text-2)]">{entry.text}</span>
                    </div>
                  ))}
                </div>
              </AGSurface>
            )}
          </div>

          <div className="flex flex-col gap-4">
            {report.what_proved?.length > 0 && (
              <AGSurface className="px-5 py-5">
                <AGSectionLabel>What Was Proved</AGSectionLabel>
                <ul className="mt-4 space-y-2">
                  {report.what_proved.map((item) => (
                    <li key={item} className="flex gap-3 text-sm leading-6 text-[var(--ag-text-1)]">
                      <span className="mt-0.5 shrink-0 text-[var(--ag-green)]">✓</span>{item}
                    </li>
                  ))}
                </ul>
              </AGSurface>
            )}

            {report.what_not_proved?.length > 0 && (
              <AGSurface className="px-5 py-5">
                <AGSectionLabel>What Remains Unproven</AGSectionLabel>
                <ul className="mt-4 space-y-2">
                  {report.what_not_proved.map((item) => (
                    <li key={item} className="flex gap-3 text-sm leading-6 text-[var(--ag-text-2)]">
                      <span className="mt-0.5 shrink-0 text-[var(--ag-red)]">○</span>{item}
                    </li>
                  ))}
                </ul>
              </AGSurface>
            )}

            {report.key_quotes?.filter(Boolean).length > 0 && (
              <AGSurface className="px-5 py-5">
                <AGSectionLabel>Candidate Quotes</AGSectionLabel>
                <div className="mt-4 space-y-3">
                  {report.key_quotes.filter(Boolean).map((quote) => (
                    <blockquote key={quote} className="border-l-2 border-[var(--ag-border-strong)] pl-4 text-sm italic leading-7 text-[var(--ag-text-2)]">
                      {quote}
                    </blockquote>
                  ))}
                </div>
              </AGSurface>
            )}

            <AGSurface className="px-5 py-5">
              <AGSectionLabel>Test Results</AGSectionLabel>
              <div className="mt-4 space-y-2">
                {report.test_result.details.map((detail) => (
                  <div key={detail.name} className={`rounded-xl border px-3 py-2.5 ${statusPalette(detail.status)}`}>
                    <div className="flex items-center justify-between gap-3">
                      <p className="text-sm leading-5 text-[var(--ag-text-1)]">{detail.name}</p>
                      <span className="shrink-0 font-mono text-[10px] uppercase">
                        {detail.visibility === "hidden" ? "hidden · " : ""}{detail.status}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            </AGSurface>
          </div>
        </div>
      </div>
    </main>
  );
}
