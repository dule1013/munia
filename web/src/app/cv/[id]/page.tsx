import { notFound } from "next/navigation";
import { CvEditor } from "@/components/cv-editor";
import { serverApi } from "@/lib/api-server";
import type { TailoredCv } from "@/lib/api-client";
import { tailoredCvLibrary } from "@/lib/career-ops";
import { portalMode } from "@/lib/portal-mode.mjs";

export const dynamic = "force-dynamic";

export default async function TailoredCvPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  if (!portalMode()) {
    const cv = (await tailoredCvLibrary()).find((item) => item.reportId === String(Number(id)));
    if (!cv?.editable) notFound();
    return <CvEditor mode="tailored" reportId={cv.reportId} applicationId={cv.applicationId} company={cv.company} role={cv.role} pdfReady={cv.pdfReady} />;
  }
  let cv: TailoredCv;
  try {
    cv = await serverApi<TailoredCv>(`/cvs/${encodeURIComponent(id)}`);
  } catch {
    notFound();
  }
  return <CvEditor mode="tailored" reportId={cv.id} applicationId={cv.candidate_job_id} company={cv.company} role={cv.title} pdfReady={cv.pdf_ready} />;
}
