import { notFound } from "next/navigation";
import Link from "next/link";

type Weakness = {
  type: string;
  severity: string;
  weakness: string;
  attack_strategy: string;
};

type Report = {
  session_id: string;
  scores: Record<string, number>;
  weakness_summary: Record<string, number>;
  total_questions: number;
  failure_surface: Record<string, number>;
  raw_weaknesses: Weakness[];
};

async function getReport(sessionId: string): Promise<Report> {
  const res = await fetch(
    `${process.env.NEXT_PUBLIC_API_URL}/report/${sessionId}`,
    { cache: "no-store" }
  );
  if (!res.ok) notFound();
  return res.json();
}

function severityColor(pct: number) {
  if (pct >= 0.7) return "bg-red-500";
  if (pct >= 0.4) return "bg-yellow-500";
  return "bg-green-500";
}

export default async function ReportPage({
  params,
}: {
  params: { session_id: string };
}) {
  const report = await getReport(params.session_id);

  const weaknessTypes = Object.entries(report.weakness_summary);
  const failureSurface = Object.entries(report.failure_surface);

  // Simple hire recommendation based on failure surface
  const avgFailure =
    failureSurface.length > 0
      ? failureSurface.reduce((s, [, v]) => s + v, 0) / failureSurface.length
      : 0;
  const recommendation =
    avgFailure < 0.3 ? "HIRE" : avgFailure < 0.6 ? "MAYBE" : "NO HIRE";
  const recColor =
    recommendation === "HIRE"
      ? "text-green-400"
      : recommendation === "MAYBE"
      ? "text-yellow-400"
      : "text-red-400";

  return (
    <main className="min-h-screen bg-black text-white px-6 py-10">
      <div className="max-w-3xl mx-auto space-y-10">
        {/* Header */}
        <div className="flex items-start justify-between">
          <div>
            <h1 className="text-2xl font-bold">Interview Report</h1>
            <p className="text-zinc-500 text-sm mt-1 font-mono">{report.session_id}</p>
          </div>
          <span className={`text-2xl font-bold ${recColor}`}>{recommendation}</span>
        </div>

        {/* Stats row */}
        <div className="grid grid-cols-3 gap-4">
          {[
            { label: "Questions", value: report.total_questions },
            { label: "Weaknesses", value: report.raw_weaknesses.length },
            {
              label: "High Severity",
              value: report.raw_weaknesses.filter((w) => w.severity === "high").length,
            },
          ].map(({ label, value }) => (
            <div key={label} className="bg-zinc-900 rounded-xl px-5 py-4 text-center">
              <p className="text-3xl font-bold">{value}</p>
              <p className="text-zinc-500 text-xs mt-1">{label}</p>
            </div>
          ))}
        </div>

        {/* Failure surface */}
        {failureSurface.length > 0 && (
          <section className="space-y-3">
            <h2 className="text-sm font-semibold text-zinc-400 uppercase tracking-widest">
              Failure Surface
            </h2>
            {failureSurface.map(([area, score]) => (
              <div key={area}>
                <div className="flex justify-between text-sm mb-1">
                  <span className="text-zinc-300">{area.replace(/_/g, " ")}</span>
                  <span className="text-zinc-500">{Math.round(score * 100)}%</span>
                </div>
                <div className="w-full bg-zinc-800 rounded-full h-2">
                  <div
                    className={`${severityColor(score)} h-2 rounded-full transition-all`}
                    style={{ width: `${score * 100}%` }}
                  />
                </div>
              </div>
            ))}
          </section>
        )}

        {/* Weakness breakdown */}
        {weaknessTypes.length > 0 && (
          <section className="space-y-3">
            <h2 className="text-sm font-semibold text-zinc-400 uppercase tracking-widest">
              Weakness Breakdown
            </h2>
            <div className="grid grid-cols-2 gap-3">
              {weaknessTypes.map(([type, count]) => (
                <div key={type} className="bg-zinc-900 rounded-xl px-4 py-3 flex justify-between items-center">
                  <span className="text-sm text-zinc-300 capitalize">{type.replace(/_/g, " ")}</span>
                  <span className="text-lg font-bold">{count}</span>
                </div>
              ))}
            </div>
          </section>
        )}

        {/* Weakness log */}
        {report.raw_weaknesses.length > 0 && (
          <section className="space-y-3">
            <h2 className="text-sm font-semibold text-zinc-400 uppercase tracking-widest">
              Detected Weaknesses
            </h2>
            <div className="space-y-2">
              {report.raw_weaknesses.map((w, i) => (
                <div key={i} className="bg-zinc-900 rounded-xl px-4 py-3 space-y-1">
                  <div className="flex items-center gap-2">
                    <span
                      className={`text-xs px-2 py-0.5 rounded-full ${
                        w.severity === "high"
                          ? "bg-red-900 text-red-300"
                          : w.severity === "medium"
                          ? "bg-yellow-900 text-yellow-300"
                          : "bg-zinc-700 text-zinc-300"
                      }`}
                    >
                      {w.severity}
                    </span>
                    <span className="text-xs text-zinc-500 capitalize">
                      {w.type?.replace(/_/g, " ")}
                    </span>
                  </div>
                  <p className="text-sm text-zinc-200">{w.weakness}</p>
                  <p className="text-xs text-zinc-600">
                    Strategy: {w.attack_strategy?.replace(/_/g, " ")}
                  </p>
                </div>
              ))}
            </div>
          </section>
        )}

        <div className="flex gap-4 pt-4">
          <Link
            href="/"
            className="flex-1 text-center bg-white text-black font-semibold py-3 rounded-lg hover:bg-zinc-200 transition text-sm"
          >
            New Interview
          </Link>
          <Link
            href="/dashboard"
            className="flex-1 text-center bg-zinc-900 text-white font-semibold py-3 rounded-lg hover:bg-zinc-800 transition text-sm"
          >
            Dashboard
          </Link>
        </div>
      </div>
    </main>
  );
}
