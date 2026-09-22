import { notFound } from "next/navigation";
import { ReportView } from "@/components/report-view";
import { serverApi } from "@/lib/api-server";
import type { PipelineDetail } from "@/lib/api-client";
import { findApplication, pdfReadyForReport, readReport, tailoredCvLibrary, trackerCanDelete, type Application, type TailoredCv } from "@/lib/career-ops";
import { reportNumberFromCell } from "@/lib/apply/cv-selection.mjs";
import { portalMode } from "@/lib/portal-mode.mjs";

export const dynamic = "force-dynamic";

export default async function ReportPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  if (!portalMode()) {
    const app = findApplication(id);
    const report = readReport(id);
    if (!app && !report) notFound();
    const reportId = reportNumberFromCell(app?.report) ?? Number(id);
    const tailoredCv = (await tailoredCvLibrary()).find((cv) => cv.reportId === String(reportId)) ?? null;
    return <ReportView id={id} app={app} report={report?.content ?? null} file={report?.file ?? null} canDelete={trackerCanDelete()} pdfReadyFromIndex={await pdfReadyForReport(String(reportId))} tailoredCv={tailoredCv} />;
  }
  let detail: PipelineDetail;
  try {
    detail = await serverApi<PipelineDetail>(`/pipeline/${encodeURIComponent(id)}`);
  } catch {
    notFound();
  }
  const item = detail.candidate_job;
  const app: Application = {
    n: item.id,
    date: item.evaluated_at?.slice(0, 10) || item.job.first_seen_at.slice(0, 10),
    company: item.job.company,
    via: "",
    role: item.job.title,
    score: item.fit_score == null ? "" : `${item.fit_score.toFixed(1)}/5`,
    status: item.pipeline_status,
    pdf: "",
    report: "",
    notes: item.notes,
  };
  const tailoredCv: TailoredCv | null = detail.tailored_cv ? {
    reportId: detail.tailored_cv.id,
    applicationId: item.id,
    company: item.job.company,
    role: item.job.title,
    score: app.score,
    status: app.status,
    generatedDate: detail.evaluation?.evaluated_at.slice(0, 10) || app.date,
    modifiedDate: detail.evaluation?.evaluated_at.slice(0, 10) || app.date,
    format: "a4",
    pdfReady: detail.tailored_cv.pdf_ready,
    editable: true,
    manuallyEdited: detail.tailored_cv.manually_edited,
    htmlPath: null,
    pdfPath: null,
  } : null;
  return <ReportView id={id} app={app} report={detail.evaluation?.report_markdown || null} file={detail.evaluation ? `evaluation-${detail.evaluation.id}.md` : null} canDelete={false} pdfReadyFromIndex={detail.tailored_cv?.pdf_ready || false} tailoredCv={tailoredCv} jobId={item.job_id} />;
}
