"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";

import { getApiBaseUrl } from "@/lib/api";

type ReplayCase = {
  case_id: string;
  label: string;
  source_type: string;
  source_path: string;
  target_role: string;
  years_experience: string;
  candidate_name: string;
  turn_count: number;
  map_available: boolean;
  report_available: boolean;
};

type ReplayStart = {
  session_id: string;
  opening_question: string;
  turn_count: number;
  candidate_name: string;
  target_role: string;
};

const API = getApiBaseUrl();

export default function ReplayInterviewLauncherPage() {
  const router = useRouter();
  const [cases, setCases] = useState<ReplayCase[]>([]);
  const [loading, setLoading] = useState(true);
  const [startingCase, setStartingCase] = useState("");
  const [filter, setFilter] = useState("");
  const [error, setError] = useState("");
  const [lastStart, setLastStart] = useState<ReplayStart | null>(null);

  useEffect(() => {
    let alive = true;
    async function loadCases() {
      setLoading(true);
      setError("");
      try {
        const res = await fetch(`${API}/replay/cases`, { cache: "no-store" });
        const payload = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(payload?.detail || `Replay cases failed: ${res.status}`);
        if (alive) setCases(Array.isArray(payload.cases) ? payload.cases : []);
      } catch (err) {
        if (alive) setError(err instanceof Error ? err.message : "Replay case loading failed");
      } finally {
        if (alive) setLoading(false);
      }
    }
    loadCases();
    return () => {
      alive = false;
    };
  }, []);

  const visibleCases = useMemo(() => {
    const needle = filter.trim().toLowerCase();
    if (!needle) return cases;
    return cases.filter((item) =>
      [
        item.label,
        item.candidate_name,
        item.target_role,
        item.source_type,
        item.source_path,
      ]
        .join(" ")
        .toLowerCase()
        .includes(needle),
    );
  }, [cases, filter]);

  async function startCase(caseId: string, mode: "manual" | "three_turn") {
    setStartingCase(caseId);
    setError("");
    try {
      const res = await fetch(`${API}/replay/start`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ case_id: caseId, max_turns: mode === "three_turn" ? 3 : 0 }),
      });
      const payload = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(payload?.detail || `Replay start failed: ${res.status}`);
      setLastStart(payload as ReplayStart);
      router.push(`/interview-room/${encodeURIComponent(payload.session_id)}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Replay start failed");
    } finally {
      setStartingCase("");
    }
  }

  return (
    <main className="rq-page">
      <section className="rq-shell" aria-label="Replay voice QA launcher">
        <div className="rq-top">
          <div>
            <p className="rq-kicker">Replay Voice QA</p>
            <h1>Locked Room Runtime Replay</h1>
          </div>
          <div className="rq-actions">
            <input
              aria-label="Filter replay cases"
              value={filter}
              onChange={(event) => setFilter(event.target.value)}
              placeholder="Filter cases"
            />
            <button type="button" onClick={() => window.location.reload()}>
              Refresh
            </button>
          </div>
        </div>

        {error ? <div className="rq-error">{error}</div> : null}
        {lastStart ? (
          <div className="rq-started">
            <span>{lastStart.session_id}</span>
            <a href={`/interview-room/${encodeURIComponent(lastStart.session_id)}`}>Open room</a>
            <a href={`${API}/replay/qa_report/${encodeURIComponent(lastStart.session_id)}`}>QA report</a>
          </div>
        ) : null}

        <div className="rq-table-wrap">
          <table className="rq-table">
            <thead>
              <tr>
                <th>Case</th>
                <th>Role</th>
                <th>Turns</th>
                <th>Artifacts</th>
                <th>Run</th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr>
                  <td colSpan={5}>Loading replay cases...</td>
                </tr>
              ) : null}
              {!loading && visibleCases.length === 0 ? (
                <tr>
                  <td colSpan={5}>No replay cases found.</td>
                </tr>
              ) : null}
              {visibleCases.map((item) => (
                <tr key={item.case_id}>
                  <td>
                    <strong>{item.label}</strong>
                    <span>{item.candidate_name}</span>
                    <code>{item.source_path}</code>
                  </td>
                  <td>
                    <span>{item.target_role || "Candidate"}</span>
                    <small>{item.years_experience || "Experience not specified"}</small>
                  </td>
                  <td>{item.turn_count}</td>
                  <td>
                    <span className={item.map_available ? "rq-ok" : "rq-muted"}>map</span>
                    <span className={item.report_available ? "rq-ok" : "rq-muted"}>report</span>
                    <span className="rq-muted">{item.source_type}</span>
                  </td>
                  <td>
                    <div className="rq-run">
                      <button
                        type="button"
                        disabled={Boolean(startingCase)}
                        onClick={() => startCase(item.case_id, "manual")}
                      >
                        {startingCase === item.case_id ? "Starting" : "Full replay"}
                      </button>
                      <button
                        type="button"
                        disabled={Boolean(startingCase)}
                        onClick={() => startCase(item.case_id, "three_turn")}
                      >
                        3-turn
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <style jsx>{`
        .rq-page {
          min-height: 100vh;
          background: #050505;
          color: #f8f5ef;
          padding: 32px;
        }

        .rq-shell {
          max-width: 1180px;
          margin: 0 auto;
        }

        .rq-top {
          display: flex;
          align-items: end;
          justify-content: space-between;
          gap: 20px;
          margin-bottom: 18px;
        }

        .rq-kicker {
          margin: 0 0 7px;
          color: #a9f0da;
          font-size: 12px;
          text-transform: uppercase;
          letter-spacing: 0.12em;
        }

        h1 {
          margin: 0;
          font-size: 30px;
          font-weight: 650;
          letter-spacing: 0;
        }

        .rq-actions {
          display: flex;
          gap: 10px;
          align-items: center;
        }

        input,
        button {
          border: 1px solid rgba(255, 255, 255, 0.16);
          background: rgba(255, 255, 255, 0.06);
          color: #f8f5ef;
          border-radius: 8px;
          height: 38px;
          padding: 0 12px;
          font: inherit;
        }

        input {
          width: 250px;
        }

        button {
          cursor: pointer;
        }

        button:hover:not(:disabled) {
          border-color: rgba(169, 240, 218, 0.55);
          background: rgba(169, 240, 218, 0.12);
        }

        button:disabled {
          cursor: wait;
          opacity: 0.55;
        }

        .rq-error,
        .rq-started {
          margin-bottom: 14px;
          border-radius: 8px;
          border: 1px solid rgba(255, 255, 255, 0.14);
          background: rgba(255, 255, 255, 0.06);
          padding: 12px 14px;
        }

        .rq-error {
          border-color: rgba(255, 103, 103, 0.45);
          color: #ffc1c1;
        }

        .rq-started {
          display: flex;
          gap: 14px;
          align-items: center;
          color: #dffaf1;
        }

        .rq-started a {
          color: #a9f0da;
        }

        .rq-table-wrap {
          overflow: auto;
          border: 1px solid rgba(255, 255, 255, 0.12);
          border-radius: 8px;
        }

        .rq-table {
          width: 100%;
          border-collapse: collapse;
          min-width: 900px;
          background: rgba(255, 255, 255, 0.035);
        }

        th,
        td {
          padding: 14px 16px;
          text-align: left;
          border-bottom: 1px solid rgba(255, 255, 255, 0.1);
          vertical-align: top;
          font-size: 14px;
        }

        th {
          color: rgba(248, 245, 239, 0.6);
          font-size: 12px;
          text-transform: uppercase;
          letter-spacing: 0.08em;
          background: rgba(0, 0, 0, 0.4);
        }

        td strong,
        td span,
        td small,
        td code {
          display: block;
        }

        td strong {
          font-size: 15px;
          margin-bottom: 5px;
        }

        td span {
          color: rgba(248, 245, 239, 0.72);
        }

        td small {
          color: rgba(248, 245, 239, 0.52);
        }

        td code {
          max-width: 500px;
          color: rgba(248, 245, 239, 0.45);
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
          margin-top: 6px;
        }

        .rq-ok,
        .rq-muted {
          display: inline-block;
          margin-right: 10px;
        }

        .rq-ok {
          color: #a9f0da;
        }

        .rq-muted {
          color: rgba(248, 245, 239, 0.45);
        }

        .rq-run {
          display: flex;
          gap: 8px;
          flex-wrap: wrap;
        }

        @media (max-width: 760px) {
          .rq-page {
            padding: 18px;
          }

          .rq-top {
            align-items: stretch;
            flex-direction: column;
          }

          .rq-actions {
            align-items: stretch;
            flex-direction: column;
          }

          input {
            width: 100%;
          }
        }
      `}</style>
    </main>
  );
}
