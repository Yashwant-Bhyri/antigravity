import { notFound } from "next/navigation";
import Link from "next/link";
import { getApiBaseUrl } from "@/lib/api";

type Report = {
  session_id: string;
  complete: boolean;
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
  raw_weaknesses: { type: string; severity: string; weakness: string; attack_strategy: string }[];
  claim_credibility_risk: { level: string; detail: string } | null;
};

async function getReport(sessionId: string): Promise<Report> {
  const res = await fetch(
    `${getApiBaseUrl()}/report/${sessionId}`,
    { cache: "no-store" }
  );
  if (!res.ok) notFound();
  return res.json();
}

function recColor(rec: string | null) {
  if (rec === "HIRE") return "text-green-400";
  if (rec === "MAYBE") return "text-yellow-400";
  if (rec === "NO HIRE") return "text-red-400";
  if (rec === "INSUFFICIENT_DATA") return "text-sky-400";
  return "text-zinc-500";
}

function barColor(score: number, max = 10) {
  const pct = score / max;
  if (pct >= 0.7) return "bg-green-500";
  if (pct >= 0.4) return "bg-yellow-500";
  return "bg-red-500";
}

function isNumericScore(score: number | string): score is number {
  return typeof score === "number" && Number.isFinite(score);
}

export default async function ReportPage({
  params,
}: {
  params: Promise<{ session_id: string }>;
}) {
  const { session_id } = await params;
  const r = await getReport(session_id);
  const untestedDimensions = Array.isArray(r.untested_dimensions) ? r.untested_dimensions : [];

  const scoreEntries = Object.entries(r.scores);
  const failureEntries = Object.entries(r.failure_surface);
  const weaknessByType = Object.entries(r.weakness_summary);
  const highCount = r.raw_weaknesses.filter((w) => w.severity === "high").length;

  return (
    <main className="min-h-screen bg-black text-white px-6 py-10">
      <div className="max-w-3xl mx-auto space-y-10">

        {/* Header */}
        <div className="flex items-start justify-between">
          <div>
            <h1 className="text-2xl font-bold">Interview Report</h1>
            <p className="text-zinc-500 text-sm mt-1 font-mono truncate max-w-xs">{r.session_id}</p>
            {(r.target_role || r.years_experience) && (
              <div className="flex gap-2 mt-2 flex-wrap">
                {r.target_role && (
                  <span className="text-[10px] uppercase tracking-widest border border-zinc-800 rounded-full px-2 py-1 text-zinc-400">
                    {r.target_role}
                  </span>
                )}
                {r.years_experience && (
                  <span className="text-[10px] uppercase tracking-widest border border-zinc-800 rounded-full px-2 py-1 text-zinc-400">
                    {r.years_experience} YOE
                  </span>
                )}
              </div>
            )}
            {!r.complete && (
              <p className="text-yellow-500 text-xs mt-1">Interview still in progress — partial data</p>
            )}
          </div>
          <div className="text-right">
            <p className={`text-3xl font-bold ${recColor(r.hire_recommendation)}`}>
              {r.hire_recommendation ?? "—"}
            </p>
            {r.confidence_score != null && (
              <p className="text-xs text-zinc-600 mt-1">
                {Math.round(r.confidence_score * 100)}% confidence
              </p>
            )}
          </div>
        </div>

        {/* Summary */}
        {r.summary && (
          <div className="bg-zinc-900 rounded-xl px-5 py-4">
            <p className="text-sm text-zinc-300 leading-relaxed">{r.summary}</p>
          </div>
        )}

        {/* Claim Credibility Risk — separate from overall score */}
        {r.claim_credibility_risk && r.claim_credibility_risk.level !== "not_tested" && (
          <div className={`rounded-xl px-5 py-4 border ${
            r.claim_credibility_risk.level === "high"
              ? "bg-red-950/30 border-red-500/20"
              : r.claim_credibility_risk.level === "medium"
              ? "bg-yellow-950/30 border-yellow-500/20"
              : "bg-green-950/30 border-green-500/20"
          }`}>
            <p className="text-[10px] uppercase tracking-widest font-bold mb-1 text-zinc-500">Resume Claim Credibility</p>
            <div className="flex items-center gap-2 mb-1">
              <span className={`text-xs font-bold uppercase ${
                r.claim_credibility_risk.level === "high" ? "text-red-400"
                : r.claim_credibility_risk.level === "medium" ? "text-yellow-400"
                : "text-green-400"
              }`}>{r.claim_credibility_risk.level} risk</span>
            </div>
            <p className="text-sm text-zinc-400">{r.claim_credibility_risk.detail}</p>
          </div>
        )}

        {/* Stats */}
        <div className="grid grid-cols-3 gap-4">
          {[
            { label: "Overall Score", value: r.overall_score != null ? `${r.overall_score}/10` : "—" },
            { label: "Questions", value: r.total_questions },
            { label: "High Severity", value: highCount },
          ].map(({ label, value }) => (
            <div key={label} className="bg-zinc-900 rounded-xl px-5 py-4 text-center">
              <p className="text-3xl font-bold">{value}</p>
              <p className="text-zinc-500 text-xs mt-1">{label}</p>
            </div>
          ))}
        </div>

        {/* Dimension scores */}
        {scoreEntries.length > 0 && (
          <section className="space-y-3">
            <h2 className="text-xs font-semibold text-zinc-500 uppercase tracking-widest">
              Score Breakdown
            </h2>
            {scoreEntries.map(([dim, score]) => (
              <div key={dim}>
                <div className="flex justify-between text-sm mb-1">
                  <span className="text-zinc-300 capitalize">{dim.replace(/_/g, " ")}</span>
                  <span className="text-zinc-500">
                    {isNumericScore(score) ? `${score}/10` : String(score)}
                  </span>
                </div>
                {isNumericScore(score) ? (
                  <div className="w-full bg-zinc-800 rounded-full h-2">
                    <div
                      className={`${barColor(score)} h-2 rounded-full transition-all`}
                      style={{ width: `${(score / 10) * 100}%` }}
                    />
                  </div>
                ) : (
                  <div className="w-full bg-zinc-900 border border-zinc-800 rounded-lg px-3 py-2 text-xs text-zinc-500">
                    This dimension was not tested broadly enough to score confidently.
                  </div>
                )}
              </div>
            ))}
          </section>
        )}

        {untestedDimensions.length > 0 && (
          <section className="bg-zinc-900 rounded-xl px-5 py-4 space-y-2">
            <h2 className="text-xs font-semibold text-sky-400 uppercase tracking-widest">
              Untested Dimensions
            </h2>
            <ul className="space-y-1">
              {untestedDimensions.map((dim, i) => (
                <li key={`${dim}-${i}`} className="text-sm text-zinc-300">
                  • {dim}
                </li>
              ))}
            </ul>
          </section>
        )}

        {/* Failure surface */}
        {failureEntries.length > 0 && (
          <section className="space-y-3">
            <h2 className="text-xs font-semibold text-zinc-500 uppercase tracking-widest">
              Failure Surface
            </h2>
            <p className="text-xs text-zinc-600">Higher = harder failure boundary reached</p>
            {failureEntries.map(([area, score]) => (
              <div key={area}>
                <div className="flex justify-between text-sm mb-1">
                  <span className="text-zinc-300">{area.replace(/_/g, " ")}</span>
                  <span className="text-zinc-500">{Math.round(score * 100)}%</span>
                </div>
                <div className="w-full bg-zinc-800 rounded-full h-2">
                  <div
                    className={`${barColor(score * 10)} h-2 rounded-full`}
                    style={{ width: `${score * 100}%` }}
                  />
                </div>
              </div>
            ))}
          </section>
        )}

        {/* Strengths + Risk flags */}
        <div className="grid grid-cols-2 gap-4">
          {r.strengths.length > 0 && (
            <div className="bg-zinc-900 rounded-xl px-4 py-4 space-y-2">
              <h3 className="text-xs font-semibold text-green-500 uppercase tracking-widest">Strengths</h3>
              <ul className="space-y-1">
                {r.strengths.map((s, i) => (
                  <li key={i} className="text-sm text-zinc-300">• {s}</li>
                ))}
              </ul>
            </div>
          )}
          {r.risk_flags.length > 0 && (
            <div className="bg-zinc-900 rounded-xl px-4 py-4 space-y-2">
              <h3 className="text-xs font-semibold text-red-500 uppercase tracking-widest">Risk Flags</h3>
              <ul className="space-y-1">
                {r.risk_flags.map((f, i) => (
                  <li key={i} className="text-sm text-zinc-300">⚠ {f}</li>
                ))}
              </ul>
            </div>
          )}
        </div>

        {/* Weakness log */}
        {r.raw_weaknesses.length > 0 && (
          <section className="space-y-3">
            <h2 className="text-xs font-semibold text-zinc-500 uppercase tracking-widest">
              Detected Weaknesses ({r.raw_weaknesses.length})
            </h2>
            <div className="space-y-2">
              {r.raw_weaknesses.map((w, i) => (
                <div key={i} className="bg-zinc-900 rounded-xl px-4 py-3 space-y-1">
                  <div className="flex items-center gap-2">
                    <span className={`text-xs px-2 py-0.5 rounded-full ${
                      w.severity === "high" ? "bg-red-900 text-red-300"
                      : w.severity === "medium" ? "bg-yellow-900 text-yellow-300"
                      : "bg-zinc-700 text-zinc-400"
                    }`}>{w.severity}</span>
                    <span className="text-xs text-zinc-500 capitalize">{w.type?.replace(/_/g, " ")}</span>
                  </div>
                  <p className="text-sm text-zinc-200">{w.weakness}</p>
                  <p className="text-xs text-zinc-600">Strategy used: {w.attack_strategy?.replace(/_/g, " ")}</p>
                </div>
              ))}
            </div>
          </section>
        )}

        <div className="flex gap-4 pt-4">
          <Link href="/" className="flex-1 text-center bg-white text-black font-semibold py-3 rounded-lg hover:bg-zinc-200 transition text-sm">
            New Interview
          </Link>
          <Link href="/dashboard" className="flex-1 text-center bg-zinc-900 text-white font-semibold py-3 rounded-lg hover:bg-zinc-800 transition text-sm">
            Dashboard
          </Link>
        </div>
      </div>
    </main>
  );
}
