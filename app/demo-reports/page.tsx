import { ReportGallery } from "./report-gallery";
import { demoReports } from "./report-data";

export default function DemoReportsIndex() {
  return <ReportGallery reports={demoReports} />;
}
