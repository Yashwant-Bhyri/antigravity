import { notFound } from "next/navigation";

import { CandidateWorkspace } from "../../../demo-reports/[slug]/candidate/candidate-workspace";
import { getApiBaseUrl } from "@/lib/api";
import { adaptProductionReport } from "../../report-adapter";

async function getReport(sessionId: string, accessToken: string) {
  const query = new URLSearchParams({ audience: "candidate" });
  if (accessToken) query.set("access_token", accessToken);
  const response = await fetch(`${getApiBaseUrl()}/report/${encodeURIComponent(sessionId)}?${query}`, { cache: "no-store" });
  if (!response.ok) notFound();
  return response.json();
}

export default async function CandidateReportPage({ params, searchParams }: { params: Promise<{ session_id: string }>; searchParams: Promise<{ access_token?: string }> }) {
  const { session_id: sessionId } = await params;
  const { access_token: accessToken = "" } = await searchParams;
  const payload = await getReport(sessionId, accessToken);
  const report = adaptProductionReport(payload, sessionId);

  return (
    <CandidateWorkspace
      report={report}
      galleryHref="/interview-room/replay"
      galleryLabel="Interview replay"
    />
  );
}
