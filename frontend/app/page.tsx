"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

export default function Home() {
  const router = useRouter();
  const [resume, setResume] = useState("");
  const [githubLinks, setGithubLinks] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function startInterview() {
    if (!resume.trim()) {
      setError("Paste your resume text to begin.");
      return;
    }
    setLoading(true);
    setError("");

    try {
      const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/start_interview`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          resume,
          github_links: githubLinks.split("\n").map((l) => l.trim()).filter(Boolean),
        }),
      });

      const data = await res.json();
      router.push(`/interview/${data.session_id}`);
    } catch {
      setError("Failed to connect to server. Is the backend running?");
      setLoading(false);
    }
  }

  return (
    <main className="min-h-screen bg-black text-white flex flex-col items-center justify-center px-6">
      <div className="w-full max-w-2xl space-y-8">
        <div className="text-center space-y-2">
          <h1 className="text-4xl font-bold tracking-tight">Antigravity</h1>
          <p className="text-zinc-400 text-lg">AI Adversarial Interview Engine</p>
          <p className="text-zinc-600 text-sm">
            Not a quiz. Not a chatbot. A cognitive stress test.
          </p>
        </div>

        <div className="space-y-3">
          <label className="block text-sm font-medium text-zinc-300">
            Resume <span className="text-zinc-500">(paste full text)</span>
          </label>
          <textarea
            rows={10}
            value={resume}
            onChange={(e) => setResume(e.target.value)}
            placeholder="Paste your resume here..."
            className="w-full bg-zinc-900 border border-zinc-700 rounded-lg px-4 py-3 text-sm text-white placeholder-zinc-600 focus:outline-none focus:border-zinc-400 resize-none"
          />
        </div>

        <div className="space-y-3">
          <label className="block text-sm font-medium text-zinc-300">
            GitHub Links <span className="text-zinc-500">(one per line, optional)</span>
          </label>
          <textarea
            rows={3}
            value={githubLinks}
            onChange={(e) => setGithubLinks(e.target.value)}
            placeholder="https://github.com/you/project"
            className="w-full bg-zinc-900 border border-zinc-700 rounded-lg px-4 py-3 text-sm text-white placeholder-zinc-600 focus:outline-none focus:border-zinc-400 resize-none"
          />
        </div>

        {error && <p className="text-red-400 text-sm">{error}</p>}

        <button
          onClick={startInterview}
          disabled={loading}
          className="w-full bg-white text-black font-semibold py-3 rounded-lg hover:bg-zinc-200 transition disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {loading ? "Starting interview..." : "Begin Interview →"}
        </button>

        <p className="text-center text-zinc-700 text-xs">
          30 min · Voice-based · 3 sprints: Project Defense → Foundations → System Design
        </p>
      </div>
    </main>
  );
}
