import { notFound, redirect } from "next/navigation";

import { getApiBaseUrl } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function SavedReportPreviewPage({
  params,
  searchParams,
}: {
  params: Promise<{ case_id: string }>;
  searchParams: Promise<{ view?: string }>;
}) {
  const [{ case_id: caseId }, query] = await Promise.all([params, searchParams]);
  const response = await fetch(`${getApiBaseUrl()}/replay/start`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ case_id: caseId, max_turns: 0 }),
    cache: "no-store",
  });
  if (!response.ok) notFound();
  const payload = await response.json() as { session_id?: string };
  if (!payload.session_id) notFound();
  const suffix = query.view === "candidate" ? "/candidate" : "";
  redirect(`/report/${encodeURIComponent(payload.session_id)}${suffix}`);
}
