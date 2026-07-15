import { notFound } from "next/navigation";
import { demoReports, getDemoReport } from "../../report-data";
import { CandidateWorkspace } from "./candidate-workspace";

type PageProps = {
  params: Promise<{ slug: string }>;
};

export function generateStaticParams() {
  return demoReports.map((report) => ({ slug: report.slug }));
}

export default async function CandidateReflectionPage({ params }: PageProps) {
  const { slug } = await params;
  const report = getDemoReport(slug);
  if (!report) notFound();

  return <CandidateWorkspace report={report} />;
}
