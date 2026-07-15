import { notFound } from "next/navigation";
import { demoReports, getDemoReport } from "../report-data";
import { RecruiterWorkspace } from "./recruiter-workspace";

type PageProps = {
  params: Promise<{ slug: string }>;
};

export function generateStaticParams() {
  return demoReports.map((report) => ({ slug: report.slug }));
}

export default async function DemoReportPage({ params }: PageProps) {
  const { slug } = await params;
  const report = getDemoReport(slug);
  if (!report) notFound();

  const nextReports = demoReports.filter((candidate) => candidate.slug !== report.slug);
  return <RecruiterWorkspace report={report} nextReports={nextReports} />;
}
