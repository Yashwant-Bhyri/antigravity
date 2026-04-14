"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

function getApiBaseUrl() {
  const configured = process.env.NEXT_PUBLIC_API_URL?.trim();
  if (configured) {
    const normalized = configured.replace(/\/+$/, "");
    return normalized.endsWith("/api") ? normalized : `${normalized}/api`;
  }

  if (typeof window !== "undefined") {
    const host = window.location.hostname === "127.0.0.1" ? "127.0.0.1" : "localhost";
    return `http://${host}:8000/api`;
  }

  return "http://localhost:8000/api";
}

export default function Home() {
  const router = useRouter();
  const [resume, setResume] = useState("");
  const [githubLinks, setGithubLinks] = useState("");
  const [targetRole, setTargetRole] = useState("");
  const [yearsExperience, setYearsExperience] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function startInterview() {
    if (!resume.trim()) { setError("Paste your resume to begin."); return; }
    if (!targetRole.trim()) { setError("Enter the target role so we can calibrate the interview."); return; }
    if (!yearsExperience) { setError("Select the expected years-of-experience band."); return; }
    setLoading(true);
    setError("");
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 12000);

    try {
      const API_URL = getApiBaseUrl();
      const res = await fetch(`${API_URL}/start_interview`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        signal: controller.signal,
        body: JSON.stringify({
          resume,
          github_links: githubLinks.split("\n").map((l) => l.trim()).filter(Boolean),
          target_role: targetRole.trim(),
          years_experience: yearsExperience,
        }),
      });
      if (!res.ok) throw new Error(`Server error ${res.status}`);
      const data = await res.json();
      router.push(`/interview/${data.session_id}`);
    } catch (e) {
      if (e instanceof DOMException && e.name === "AbortError") {
        setError("Interview launch timed out. Please try again.");
      } else {
        setError(String(e));
      }
      setLoading(false);
    } finally {
      clearTimeout(timeout);
    }
  }

  return (
    <main className="min-h-screen bg-[#0a0a0a] text-white flex items-center justify-center px-6">
      <div className="w-full max-w-xl space-y-10">

        {/* Header */}
        <div className="space-y-3">
          <h1 className="text-3xl font-bold tracking-tight">Antigravity</h1>
          <p className="text-zinc-500 text-sm leading-relaxed">
            A 30-minute adversarial technical interview. Three sprints.
            Three interrogator personas. No hints. No validation.
          </p>
          <div className="flex gap-3 pt-1">
            {["Project Defense", "Foundations", "System Design"].map((s, i) => (
              <span key={s} className="text-[11px] text-zinc-600 border border-zinc-800 rounded px-2 py-0.5">
                {i + 1}. {s}
              </span>
            ))}
          </div>
        </div>

        <div className="space-y-4">
          {/* Resume */}
          <div className="space-y-2">
            <label className="text-xs text-zinc-500 uppercase tracking-widest">
              Resume
            </label>
            <textarea
              rows={9}
              value={resume}
              onChange={(e) => setResume(e.target.value)}
              placeholder="Paste your full resume text here..."
              className="w-full bg-white/[0.03] border border-white/[0.08] rounded-xl px-4 py-3 text-sm text-white placeholder-zinc-700 focus:outline-none focus:border-white/20 resize-none transition-colors"
            />
          </div>

          {/* GitHub */}
          <div className="space-y-2">
            <label className="text-xs text-zinc-500 uppercase tracking-widest">
              GitHub Links <span className="text-zinc-700 normal-case">(optional, one per line)</span>
            </label>
            <textarea
              rows={2}
              value={githubLinks}
              onChange={(e) => setGithubLinks(e.target.value)}
              placeholder="https://github.com/you/project"
              className="w-full bg-white/[0.03] border border-white/[0.08] rounded-xl px-4 py-3 text-sm text-white placeholder-zinc-700 focus:outline-none focus:border-white/20 resize-none transition-colors"
            />
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <label className="text-xs text-zinc-500 uppercase tracking-widest">
                Target Role
              </label>
              <input
                value={targetRole}
                onChange={(e) => setTargetRole(e.target.value)}
                placeholder="ML Engineer Intern"
                className="w-full bg-white/[0.03] border border-white/[0.08] rounded-xl px-4 py-3 text-sm text-white placeholder-zinc-700 focus:outline-none focus:border-white/20 transition-colors"
              />
            </div>

            <div className="space-y-2">
              <label className="text-xs text-zinc-500 uppercase tracking-widest">
                Years Of Experience
              </label>
              <select
                value={yearsExperience}
                onChange={(e) => setYearsExperience(e.target.value)}
                className="w-full bg-white/[0.03] border border-white/[0.08] rounded-xl px-4 py-3 text-sm text-white focus:outline-none focus:border-white/20 transition-colors"
              >
                <option value="" className="bg-black text-zinc-400">Select band</option>
                <option value="0-1" className="bg-black text-white">0-1 years</option>
                <option value="1-2" className="bg-black text-white">1-2 years</option>
                <option value="2-4" className="bg-black text-white">2-4 years</option>
                <option value="4-6" className="bg-black text-white">4-6 years</option>
                <option value="6+" className="bg-black text-white">6+ years</option>
              </select>
            </div>
          </div>

          {error && <p className="text-red-400 text-xs">{error}</p>}

          <button
            onClick={startInterview}
            disabled={loading}
            className="w-full bg-white text-black text-sm font-semibold py-3 rounded-xl hover:bg-zinc-100 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
          >
            {loading ? "Starting..." : "Begin Interview →"}
          </button>
        </div>

        <p className="text-zinc-700 text-xs text-center">
          Allow microphone access when prompted. Speak clearly and naturally.
        </p>
      </div>
    </main>
  );
}
