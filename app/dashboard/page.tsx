/**
 * Recruiter Dashboard
 * Shows all past interview sessions with scores, weaknesses, hire recommendations.
 * This is a server component — data fetched at request time.
 */

import Link from "next/link";
import { notFound } from "next/navigation";

type Session = {
  session_id: string;
  scores: Record<string, number>;
  weakness_summary: Record<string, number>;
  total_questions: number;
  failure_surface: Record<string, number>;
  raw_weaknesses: { severity: string }[];
};

// TODO: replace with a real /sessions list endpoint once backend supports it
async function getSessions(): Promise<Session[]> {
  try {
    const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/sessions`, {
      cache: "no-store",
    });
    if (!res.ok) return [];
    return res.json();
  } catch {
    return [];
  }
}

function recommendationFromSurface(surface: Record<string, number>): {
  label: string;
  color: string;
} {
  const vals = Object.values(surface);
  if (vals.length === 0) return { label: "N/A", color: "text-zinc-500" };
  const avg = vals.reduce((s, v) => s + v, 0) / vals.length;
  if (avg < 0.3) return { label: "HIRE", color: "text-green-400" };
  if (avg < 0.6) return { label: "MAYBE", color: "text-yellow-400" };
  return { label: "NO HIRE", color: "text-red-400" };
}

export default async function DashboardPage() {
  const sessions = await getSessions();

  return (
    <main className="min-h-screen bg-black text-white px-6 py-10">
      <div className="max-w-5xl mx-auto space-y-8">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold">Recruiter Dashboard</h1>
            <p className="text-zinc-500 text-sm mt-1">
              {sessions.length} interview{sessions.length !== 1 ? "s" : ""} completed
            </p>
          </div>
          <Link
            href="/"
            className="bg-white text-black text-sm font-semibold px-4 py-2 rounded-lg hover:bg-zinc-200 transition"
          >
            + New Interview
          </Link>
        </div>

        {sessions.length === 0 ? (
          <div className="text-center py-24 text-zinc-600">
            <p className="text-lg">No interviews yet.</p>
            <p className="text-sm mt-2">Start one from the home page.</p>
          </div>
        ) : (
          <div className="space-y-3">
            {/* Table header */}
            <div className="grid grid-cols-5 text-xs text-zinc-500 uppercase tracking-widest px-4">
              <span className="col-span-2">Session</span>
              <span>Questions</span>
              <span>Weaknesses</span>
              <span>Verdict</span>
            </div>

            {sessions.map((s) => {
              const rec = recommendationFromSurface(s.failure_surface);
              const highCount = s.raw_weaknesses.filter((w) => w.severity === "high").length;

              return (
                <Link
                  key={s.session_id}
                  href={`/report/${s.session_id}`}
                  className="grid grid-cols-5 items-center bg-zinc-900 rounded-xl px-4 py-4 hover:bg-zinc-800 transition text-sm"
                >
                  <span className="col-span-2 font-mono text-xs text-zinc-400 truncate">
                    {s.session_id}
                  </span>
                  <span>{s.total_questions}</span>
                  <span>
                    {s.raw_weaknesses.length}
                    {highCount > 0 && (
                      <span className="ml-2 text-xs text-red-400">
                        ({highCount} high)
                      </span>
                    )}
                  </span>
                  <span className={`font-bold ${rec.color}`}>{rec.label}</span>
                </Link>
              );
            })}
          </div>
        )}
      </div>
    </main>
  );
}
