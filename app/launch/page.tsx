"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { AGButton, AGChip, AGLogo, AGSectionLabel, AGSurface } from "@/components/design-system";
import { getApiBaseUrl } from "@/lib/api";

type LaunchState = "validating" | "starting" | "redirecting" | "failed";

export default function LaunchPage() {
  const router = useRouter();
  const [state, setState] = useState<LaunchState>("validating");
  const [message, setMessage] = useState("Validating ProvenHire handoff");

  useEffect(() => {
    let cancelled = false;
    const token = new URLSearchParams(window.location.search).get("token")?.trim() || "";
    if (!token) {
      setState("failed");
      setMessage("Launch token is missing.");
      return;
    }

    void (async () => {
      try {
        setState("starting");
        setMessage("Preparing your standalone Antigravity room");
        const res = await fetch(`${getApiBaseUrl()}/provenhire_handoff/consume`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ token }),
        });
        const payload = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(payload?.detail || payload?.error || `Launch failed (${res.status})`);
        if (cancelled) return;

        const sessionId = String(payload.session_id || "");
        if (!sessionId) throw new Error("Antigravity did not return a session id.");
        const returnUrl = typeof payload.return_url === "string" ? payload.return_url : "";
        if (returnUrl) {
          window.localStorage.setItem(`ag:return-url:${sessionId}`, returnUrl);
        }
        setState("redirecting");
        setMessage("Opening the live interview");
        router.replace(`/interview/${sessionId}`);
      } catch (e) {
        if (cancelled) return;
        setState("failed");
        setMessage(e instanceof Error ? e.message : "Could not launch Antigravity.");
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [router]);

  return (
    <main className="ag-shell flex min-h-screen items-center justify-center px-6 py-10 text-[var(--ag-text-0)]">
      <AGSurface className="w-full max-w-xl px-7 py-7">
        <div className="space-y-7">
          <div className="flex items-center justify-between gap-4">
            <AGLogo compact />
            <AGChip active>ProvenHire Handoff</AGChip>
          </div>

          <div className="space-y-3">
            <AGSectionLabel>{state === "failed" ? "Launch Failed" : "Launch Protocol"}</AGSectionLabel>
            <h1 className="text-3xl font-semibold tracking-[-0.04em]">
              {state === "failed" ? "We could not open the interview." : "Opening Antigravity."}
            </h1>
            <p className="text-sm leading-7 text-[var(--ag-text-2)]">{message}</p>
          </div>

          {state !== "failed" ? (
            <div className="h-2 overflow-hidden rounded-full bg-[var(--ag-surface-2)]">
              <div className="h-full w-2/3 animate-pulse rounded-full bg-[var(--ag-blue)] shadow-[0_0_18px_var(--ag-blue)]" />
            </div>
          ) : (
            <div className="flex flex-col gap-3 sm:flex-row">
              <AGButton href="/" variant="secondary">Open Antigravity Home</AGButton>
            </div>
          )}
        </div>
      </AGSurface>
    </main>
  );
}
