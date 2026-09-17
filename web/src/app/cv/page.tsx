import { CvLibrary } from "@/components/cv-library";
import { serverApi } from "@/lib/api-server";
import type { CandidateJob, CandidateProfile, TailoredCv as PortalTailoredCv } from "@/lib/api-client";
import { masterCvInfo, tailoredCvLibrary, type TailoredCv } from "@/lib/career-ops";
import { portalMode } from "@/lib/portal-mode.mjs";

export const dynamic = "force-dynamic";

export default async function CvPage() {
  if (!portalMode()) return <CvLibrary master={masterCvInfo()} tailored={await tailoredCvLibrary()} />;
  const [profile, cvs, pipeline] = await Promise.all([
    serverApi<CandidateProfile>("/candidate/profile"),
    serverApi<PortalTailoredCv[]>("/cvs"),
    serverApi<CandidateJob[]>("/pipeline"),
  ]);
  const states = new Map(pipeline.map((item) => [item.id, item]));
  const tailored: TailoredCv[] = cvs.map((cv) => {
    const item = states.get(cv.candidate_job_id);
    return {
      reportId: cv.id,
      applicationId: cv.candidate_job_id,
      company: cv.company,
      role: cv.title,
      score: item?.fit_score == null ? "" : `${item.fit_score.toFixed(1)}/5`,
      status: item?.pipeline_status || "Evaluated",
      generatedDate: cv.generated_at.slice(0, 10),
      modifiedDate: cv.modified_at.slice(0, 10),
      format: "a4",
      pdfReady: cv.pdf_ready,
      editable: true,
      manuallyEdited: cv.manually_edited,
      htmlPath: null,
      pdfPath: null,
    };
  });
  return <CvLibrary master={{ name: `${profile.user.name} — Master CV`, modifiedDate: profile.updated_at.slice(0, 10), exists: Boolean(profile.master_cv) }} tailored={tailored} />;
}
