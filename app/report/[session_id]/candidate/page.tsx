import { notFound } from "next/navigation";

import { CandidateWorkspace } from "../../../demo-reports/[slug]/candidate/candidate-workspace";
import { getApiBaseUrl } from "@/lib/api";
import { adaptProductionReport } from "../../report-adapter";

async function getReport(sessionId: string) {
  const response = await fetch(`${getApiBaseUrl()}/report/${encodeURIComponent(sessionId)}`, { cache: "no-store" });
  if (!response.ok) notFound();
  return response.json();
}

export default async function CandidateReportPage({ params }: { params: Promise<{ session_id: string }> }) {
  const { session_id: sessionId } = await params;
  const payload = await getReport(sessionId);
  const report = adaptProductionReport(payload, sessionId);

  return (
    <CandidateWorkspace
      report={report}
      galleryHref="/interview-room/replay"
      galleryLabel="Interview replay"
    />
  );
}
