import { notFound } from "next/navigation";
import Link from "next/link";

type Report = {
  session_id: string;
  complete: boolean;
  total_questions: number;
  overall_score: number | null;
  hire_recommendation: string | null;
  confidence_score: number | null;
  summary: string | null;
  strengths: string[];
  risk_flags: string[];
  scores: Record<string, number>;
  failure_surface: Record<string, number>;
  weakness_summary: Record<string, number>;
  raw_weaknesses: { type: string; severity: string; weakness: string; attack_strategy: string }[];
};

async function getReport(sessionId: string): Promise<Report> {
  const res = await fetch(
    `${process.env.NEXT_PUBLIC_API_URL}/report/${sessionId}`,
    { cache: "no-store" }
  );
  if (!res.ok) notFound();
  return res.json();
}

function recColor(rec: string | null) {
  if (rec === "HIRE") return "text-green-400";
  if (rec === "MAYBE") return "text-yellow-400";
  if (rec === "NO HIRE") return "text-red-400";
  return "text-zinc-500";
}

function barColor(score: number, max = 10) {
  const pct = score / max;
  if (pct >= 0.7) return "bg-green-500";
  if (pct >= 0.4) return "bg-yellow-500";
  return "bg-red-500";
}

export default async function ReportPage({
  params,
}: {
  params: Promise<{ session_id: string }>;
}) {
  const { session_id } = await params;
  const r = await getReport(session_id);

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
                  <span className="text-zinc-500">{score}/10</span>
                </div>
                <div className="w-full bg-zinc-800 rounded-full h-2">
                  <div
                    className={`${barColor(score)} h-2 rounded-full transition-all`}
                    style={{ width: `${(score / 10) * 100}%` }}
                  />
                </div>
              </div>
            ))}
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
