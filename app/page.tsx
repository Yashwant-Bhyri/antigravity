"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { AGButton, AGChip, AGLogo, AGSectionLabel, AGSurface } from "@/components/design-system";
import { getApiBaseUrl } from "@/lib/api";

const SPRINTS = [
  {
    num: 1,
    name: "Project Defense",
    desc: "Resume claims are stressed until ownership or ambiguity becomes obvious.",
  },
  {
    num: 2,
    name: "Foundations",
    desc: "Core concepts are rebuilt from first principles under live pressure.",
  },
  {
    num: 3,
    name: "System Design",
    desc: "Tradeoffs, failure modes, and scale decisions are pushed until they bend.",
  },
];

const YOE_OPTIONS = [
  { value: "0-1", label: "0-1 yrs" },
  { value: "1-2", label: "1-2 yrs" },
  { value: "2-4", label: "2-4 yrs" },
  { value: "4-6", label: "4-6 yrs" },
  { value: "6+", label: "6+ yrs" },
];

function fieldClassName() {
  return "w-full rounded-xl border border-[var(--ag-border)] bg-[var(--ag-surface-0)] px-4 py-3 text-sm text-[var(--ag-text-0)] placeholder:text-[var(--ag-text-3)] outline-none transition-all focus:border-[var(--ag-border-strong)] focus:bg-[var(--ag-surface-1)]";
}

export default function Home() {
  const router = useRouter();
  const [resume, setResume] = useState("");
  const [githubLinks, setGithubLinks] = useState("");
  const [targetRole, setTargetRole] = useState("");
  const [yearsExperience, setYearsExperience] = useState("");
  const [loading, setLoading] = useState(false);
  const [loadingStage, setLoadingStage] = useState<"permissions" | "preparing" | "starting" | "">("");
  const [error, setError] = useState("");

  useEffect(() => {
    fetch(`${getApiBaseUrl()}/tts_health`, { cache: "no-store" }).catch(() => {});
  }, []);

  async function ensureMediaPermissions() {
    if (!navigator.mediaDevices?.getUserMedia) {
      throw new Error("This browser cannot request microphone and camera permissions.");
    }
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true, video: true });
    stream.getTracks().forEach((track) => track.stop());
  }

  async function startInterview() {
    if (!resume.trim()) {
      setError("Paste the candidate resume to begin.");
      return;
    }
    if (!targetRole.trim()) {
      setError("Enter the target role so the interview calibrates correctly.");
      return;
    }
    if (!yearsExperience) {
      setError("Select the expected experience band.");
      return;
    }

    setLoading(true);
    setLoadingStage("permissions");
    setError("");
    try {
      await ensureMediaPermissions();
    } catch (e) {
      setError(`Microphone and camera access are required before the interview can start: ${String(e)}`);
      setLoading(false);
      setLoadingStage("");
      return;
    }

    setLoadingStage("preparing");
    const prepareController = new AbortController();
    const prepareTimeout = setTimeout(() => prepareController.abort(), 245000);

    try {
      const prepareRes = await fetch(`${getApiBaseUrl()}/prepare_interview_map`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        signal: prepareController.signal,
        body: JSON.stringify({
          resume,
          github_links: githubLinks
            .split("\n")
            .map((line) => line.trim())
            .filter(Boolean),
          target_role: targetRole.trim(),
          years_experience: yearsExperience,
        }),
      });
      const prepareData = await prepareRes.json().catch(() => ({}));
      if (!prepareRes.ok) {
        throw new Error(prepareData?.detail || `Map preparation failed (${prepareRes.status})`);
      }
      if (prepareData?.map_status !== "ready") {
        throw new Error("Interview map did not reach ready state.");
      }

      clearTimeout(prepareTimeout);
      setLoadingStage("starting");

      const startController = new AbortController();
      const startTimeout = setTimeout(() => startController.abort(), 30000);
      try {
        const startRes = await fetch(`${getApiBaseUrl()}/start_interview`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          signal: startController.signal,
          body: JSON.stringify({
            prepared_session_id: prepareData.session_id,
          }),
        });
        const startData = await startRes.json().catch(() => ({}));
        if (!startRes.ok) {
          throw new Error(startData?.detail || `Server error ${startRes.status}`);
        }
        router.push(`/interview/${startData.session_id}`);
      } finally {
        clearTimeout(startTimeout);
      }
    } catch (e) {
      if (e instanceof DOMException && e.name === "AbortError") {
        setError("Interview map preparation timed out. Please try again.");
      } else {
        setError(String(e));
      }
      setLoading(false);
      setLoadingStage("");
    } finally {
      clearTimeout(prepareTimeout);
    }
  }

  return (
    <main className="ag-shell min-h-screen px-6 py-10 text-[var(--ag-text-0)] md:px-10">
      <div className="mx-auto flex min-h-[calc(100vh-5rem)] w-full max-w-6xl items-center">
        <div className="grid w-full gap-8 lg:grid-cols-[1.05fr_0.95fr]">
          <div className="flex flex-col justify-between gap-8">
            <div className="space-y-8">
              <AGLogo />

              <div className="space-y-5">
                <div className="flex flex-wrap gap-2">
                  <AGChip active>Adversarial Interview Engine</AGChip>
                  <AGChip>Realtime Voice Loop</AGChip>
                  <AGChip>Three Sprint Flow</AGChip>
                </div>

                <div className="space-y-4">
                  <h1 className="max-w-3xl text-4xl font-semibold leading-[1.05] tracking-[-0.05em] text-[var(--ag-text-0)] md:text-6xl">
                    Adversarial technical interviews that actually feel
                    <span className="block text-[var(--ag-text-2)]">deliberate, sharp, and alive.</span>
                  </h1>
                  <p className="max-w-2xl text-sm leading-7 text-[var(--ag-text-2)] md:text-base">
                    Antigravity is not a quiz engine and not a friendly chatbot. It probes ownership,
                    fundamentals, and systems thinking through a live three-sprint interrogation loop.
                  </p>
                </div>
              </div>

              <div className="grid gap-3 md:grid-cols-3">
                {SPRINTS.map((sprint) => (
                  <AGSurface key={sprint.num} className="px-4 py-4">
                    <p className="font-mono text-[10px] font-semibold uppercase tracking-[0.18em] text-[var(--ag-blue)]">
                      S{sprint.num}
                    </p>
                    <h2 className="mt-2 text-sm font-semibold text-[var(--ag-text-0)]">{sprint.name}</h2>
                    <p className="mt-2 text-xs leading-6 text-[var(--ag-text-2)]">{sprint.desc}</p>
                  </AGSurface>
                ))}
              </div>
            </div>

            <div className="flex flex-wrap items-center gap-3 text-xs text-[var(--ag-text-3)]">
              <span>~30 minute session</span>
              <span className="h-1 w-1 rounded-full bg-[var(--ag-border-strong)]" />
              <span>Mic + camera required</span>
              <span className="h-1 w-1 rounded-full bg-[var(--ag-border-strong)]" />
              <span>Resume-grounded pressure test</span>
            </div>
          </div>

          <AGSurface className="px-6 py-6 md:px-8 md:py-8">
            <div className="space-y-6">
              <div className="space-y-3">
                <AGSectionLabel>Launch Interview</AGSectionLabel>
                <h2 className="text-2xl font-semibold tracking-[-0.03em] text-[var(--ag-text-0)]">
                  Feed the protocol clean input.
                </h2>
                <p className="text-sm leading-7 text-[var(--ag-text-2)]">
                  We use the candidate&apos;s resume, target role, and experience band to calibrate the
                  first attack surface before the live interview loop begins.
                </p>
              </div>

              <div className="space-y-5">
                <div className="space-y-2">
                  <AGSectionLabel>Resume</AGSectionLabel>
                  <textarea
                    rows={8}
                    value={resume}
                    onChange={(e) => setResume(e.target.value)}
                    placeholder="Paste the full resume text here…"
                    className={fieldClassName()}
                  />
                </div>

                <div className="space-y-2">
                  <AGSectionLabel>GitHub Links</AGSectionLabel>
                  <textarea
                    rows={3}
                    value={githubLinks}
                    onChange={(e) => setGithubLinks(e.target.value)}
                    placeholder="https://github.com/you/project"
                    className={fieldClassName()}
                  />
                </div>

                <div className="grid gap-4 md:grid-cols-2">
                  <div className="space-y-2">
                    <AGSectionLabel>Target Role</AGSectionLabel>
                    <input
                      value={targetRole}
                      onChange={(e) => setTargetRole(e.target.value)}
                      placeholder="ML Engineer Intern"
                      className={fieldClassName()}
                    />
                  </div>

                  <div className="space-y-2">
                    <AGSectionLabel>Experience</AGSectionLabel>
                    <select
                      value={yearsExperience}
                      onChange={(e) => setYearsExperience(e.target.value)}
                      className={fieldClassName()}
                    >
                      <option value="">Select band</option>
                      {YOE_OPTIONS.map((option) => (
                        <option key={option.value} value={option.value}>
                          {option.label}
                        </option>
                      ))}
                    </select>
                  </div>
                </div>

                {error && (
                  <div className="rounded-xl border border-[oklch(0.66_0.21_24_/_0.3)] bg-[oklch(0.66_0.21_24_/_0.08)] px-4 py-3 text-sm text-[var(--ag-red)]">
                    {error}
                  </div>
                )}

                <div className="space-y-3 pt-2">
                  <AGButton onClick={startInterview} disabled={loading} className="w-full">
                    {loading
                      ? loadingStage === "permissions"
                        ? "Checking mic + camera…"
                        : loadingStage === "starting"
                        ? "Starting interview…"
                        : "Preparing interview map…"
                      : "Begin Interview →"}
                  </AGButton>
                  <p className="text-center text-xs text-[var(--ag-text-3)]">
                    We request microphone and camera access before launch, then build the questioning map before the live interview engages.
                  </p>
                </div>
              </div>
            </div>
          </AGSurface>
        </div>
      </div>
    </main>
  );
}
