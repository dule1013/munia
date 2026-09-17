export type PortalUser = { id: string; email: string; name: string; created_at: string; updated_at: string };
export type CandidateProfile = { user: PortalUser; profile: Record<string, unknown>; master_cv: string; onboarding_complete: boolean; updated_at: string };
export type SharedJob = { id: string; company: string; title: string; location: string; description: string | null; source: string; posting_url: string; direct_application_url: string | null; posted_at: string | null; first_seen_at: string; last_seen_at: string; is_active: boolean };
export type CandidateJob = { id: string; user_id: string; job_id: string; eligibility: string | null; triage_result: "worth" | "uncertain" | "discard" | null; triage_reason: string | null; triage_metadata: Record<string, unknown>; fit_score: number | null; recommendation: string | null; pipeline_status: string; saved: boolean; skipped: boolean; notes: string; evaluated_at: string | null; applied_at: string | null; job: SharedJob };
export type TailoredCv = { id: string; job_id: string; candidate_job_id: string; evaluation_id: string | null; company: string; title: string; source_html?: string | null; pdf_ready: boolean; manually_edited: boolean; validation_status: string; generated_at: string; modified_at: string };
export type Evaluation = { id: string; candidate_job_id: string; report_number: number | null; score: number | null; recommendation: string | null; report_markdown: string; evaluated_at: string };
export type PipelineDetail = { candidate_job: CandidateJob; evaluation: Evaluation | null; tailored_cv: { id: string; pdf_ready: boolean; manually_edited: boolean } | null };

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api/backend${path}`, { ...init, headers: { "Content-Type": "application/json", ...init?.headers } });
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(error.detail || error.error || "Request failed");
  }
  return response.json() as Promise<T>;
}

export const portalApi = {
  bootstrap: () => request<PortalUser>("/candidate/bootstrap", { method: "POST" }),
  profile: () => request<CandidateProfile>("/candidate/profile"),
  onboard: (data: Record<string, unknown>) => request<CandidateProfile>("/candidate/onboarding", { method: "POST", body: JSON.stringify(data) }),
  saveProfile: (profile: Record<string, unknown>) => request<CandidateProfile>("/candidate/profile", { method: "PUT", body: JSON.stringify({ profile }) }),
  saveMasterCv: (content: string) => request<CandidateProfile>("/candidate/master-cv", { method: "PUT", body: JSON.stringify({ content }) }),
  jobs: () => request<SharedJob[]>("/jobs"),
  pipeline: () => request<CandidateJob[]>("/pipeline"),
  updateCandidateJob: (id: string, data: Partial<CandidateJob>) => request<CandidateJob>(`/pipeline/${id}`, { method: "PATCH", body: JSON.stringify(data) }),
  tailoredCvs: () => request<TailoredCv[]>("/cvs"),
  tailoredCv: (id: string) => request<TailoredCv>(`/cvs/${id}`),
  saveTailoredCv: (id: string, source_html: string) => request<TailoredCv>(`/cvs/${id}`, { method: "PUT", body: JSON.stringify({ source_html }) }),
};
