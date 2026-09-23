export type PortalUser = { id: string; email: string; name: string; created_at: string; updated_at: string };
export type CandidateProfile = { user: PortalUser; profile: Record<string, unknown>; master_cv: string; onboarding_complete: boolean; updated_at: string };
export type SharedJob = { id: string; company: string; title: string; location: string; description: string | null; source: string; posting_url: string; direct_application_url: string | null; posted_at: string | null; first_seen_at: string; last_seen_at: string; is_active: boolean };
export type CandidateJob = { id: string; user_id: string; job_id: string; eligibility: string | null; triage_result: "worth" | "uncertain" | "discard" | null; triage_reason: string | null; triage_metadata: Record<string, unknown>; fit_score: number | null; recommendation: string | null; pipeline_status: string; saved: boolean; skipped: boolean; notes: string; evaluated_at: string | null; applied_at: string | null; ai_fit: "strong" | "plausible" | "reject" | null; ai_fit_reason: string | null; ai_fit_confidence: "high" | "low" | null; ai_fit_assessed_at: string | null; job: SharedJob };
export type TodaySummary = { new: number; current: number };
export type TailoredCv = { id: string; job_id: string; candidate_job_id: string; evaluation_id: string | null; company: string; title: string; source_html?: string | null; pdf_ready: boolean; manually_edited: boolean; validation_status: string; generated_at: string; modified_at: string };
export type Evaluation = { id: string; candidate_job_id: string; report_number: number | null; score: number | null; recommendation: string | null; report_markdown: string; evaluated_at: string };
export type PipelineDetail = { candidate_job: CandidateJob; evaluation: Evaluation | null; tailored_cv: { id: string; pdf_ready: boolean; manually_edited: boolean } | null };
export type DiscoveryRunResult = { offers?: import("@/lib/explore").DiscoveredOffer[]; companiesScanned?: number; companiesAvailable?: number; capHit?: boolean; datasetStatus?: Record<string, string>; postingsDroppedNoDate?: number; unreachableBoards?: number; [key: string]: unknown };
export type DiscoveryRun = { id: string; status: "queued" | "running" | "succeeded" | "failed"; request: Record<string, unknown>; result: DiscoveryRunResult | null; error: string | null; created_at: string; started_at: string | null; finished_at: string | null };

// ── Discovery/Sources, Company Watchlist, LinkedIn (Phase 5 Checkpoint E) ──
export type SourceMetrics = { discovered: number; eligible: number; worth_evaluating: number; applied: number };
export type SourceEntry = { id: string; label: string; status?: string; last_sync_at?: string | null; last_error?: string | null; metrics?: SourceMetrics; metrics_available?: boolean };
export type WatchlistCompanyBrief = { id: string; company_name: string; careers_url: string | null; provider: string | null; enabled: boolean; scan_status: string | null; last_scanned_at: string | null; last_scan_error: string | null };
export type SourceGroup = { id: string; label: string; sources?: SourceEntry[]; summary?: { companies_watched: number; last_scan_at: string | null; errors: number }; metrics?: SourceMetrics; companies?: WatchlistCompanyBrief[] };
export type SourcesOverview = { groups: SourceGroup[] };

export type WatchedCompany = { id: string; company_name: string; careers_url: string | null; provider: string | null; provider_tenant_id: string | null; priority: number; enabled: boolean; last_scanned_at: string | null; scan_status: string | null; last_scan_error: string | null; created_at: string; updated_at: string };
export type WatchedCompanyInput = { company_name: string; careers_url?: string | null; priority?: number; enabled?: boolean };

// ── Candidate AI configuration + hosted AI Search (Phase 5 follow-up) ──────
export type AIModelOption = { id: string; label: string; cost_note: string };
export type AIConfigStatus = { configured: boolean; provider: string | null; model: string | null; updated_at: string | null; available_models: AIModelOption[] };
export type AIConfigInput = { provider?: string; model: string; api_key: string };
export type AISearchResult = { status: "ok" | "error"; error: string | null; jobs_found: number; jobs_created: number; jobs_attached: number };

export type IntegrationStatus = { connected: boolean; provider: string; status: string; account_email: string | null; scopes: string | null; last_sync_at: string | null; last_sync_status: string | null; last_error: string | null };
export type SyncResult = { status: string; messages_scanned: number; messages_skipped_untrusted: number; messages_skipped_malformed: number; jobs_found: number; jobs_created: number; jobs_attached: number; error: string | null };
export type MorningStatus = { status: "never_run" | "running" | "completed" | "completed_with_warnings" | "failed"; started_at: string | null; finished_at: string | null; sources: Record<string, string> };

export type JobDiscoveryEntry = { source: string; method: string; first_seen_at: string; last_seen_at: string };

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api/backend${path}`, { ...init, headers: { "Content-Type": "application/json", ...init?.headers } });
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(error.detail || error.error || "Request failed");
  }
  // 204 (and any other empty-body response, e.g. gmail/ai-config DELETE)
  // has nothing for .json() to parse — it throws "Unexpected end of JSON
  // input" rather than resolving, which every void-typed caller here
  // (gmailDisconnect, removeAiConfig, ...) would otherwise silently choke
  // on as an unhandled rejection.
  if (response.status === 204) {
    return undefined as T;
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
  inbox: () => request<CandidateJob[]>("/pipeline/inbox"),
  today: () => request<CandidateJob[]>("/pipeline/today"),
  todaySummary: () => request<TodaySummary>("/pipeline/today/summary"),
  updateCandidateJob: (id: string, data: Partial<CandidateJob>) => request<CandidateJob>(`/pipeline/${id}`, { method: "PATCH", body: JSON.stringify(data) }),
  tailoredCvs: () => request<TailoredCv[]>("/cvs"),
  tailoredCv: (id: string) => request<TailoredCv>(`/cvs/${id}`),
  saveTailoredCv: (id: string, source_html: string) => request<TailoredCv>(`/cvs/${id}`, { method: "PUT", body: JSON.stringify({ source_html }) }),
  createDiscoveryRun: (data: { since_days: number; ats: string[]; limit_per_ats: number }) => request<DiscoveryRun>("/discovery/runs", { method: "POST", body: JSON.stringify(data) }),
  discoveryRun: (id: string) => request<DiscoveryRun>(`/discovery/runs/${id}`),
  latestDiscoveryRun: () => request<DiscoveryRun>("/discovery/runs/latest"),
  sourcesOverview: () => request<SourcesOverview>("/discovery/sources"),
  morningStatus: () => request<MorningStatus>("/discovery/morning-status"),
  jobDiscoveries: (jobId: string) => request<JobDiscoveryEntry[]>(`/jobs/${jobId}/discoveries`),

  watchlist: () => request<WatchedCompany[]>("/discovery/watchlist"),
  addWatchedCompany: (data: WatchedCompanyInput) => request<WatchedCompany>("/discovery/watchlist", { method: "POST", body: JSON.stringify(data) }),
  updateWatchedCompany: (id: string, data: Partial<WatchedCompanyInput>) => request<WatchedCompany>(`/discovery/watchlist/${id}`, { method: "PATCH", body: JSON.stringify(data) }),
  removeWatchedCompany: (id: string) => request<void>(`/discovery/watchlist/${id}`, { method: "DELETE" }),

  gmailStatus: () => request<IntegrationStatus>("/integrations/gmail/status"),
  gmailConnect: () => request<{ authorization_url: string; state: string }>("/integrations/gmail/connect", { method: "POST" }),
  gmailDisconnect: () => request<void>("/integrations/gmail/disconnect", { method: "POST" }),
  gmailSyncNow: () => request<SyncResult>("/integrations/gmail/sync", { method: "POST" }),

  aiConfigStatus: () => request<AIConfigStatus>("/ai-config/status"),
  setAiConfig: (data: AIConfigInput) => request<AIConfigStatus>("/ai-config", { method: "PUT", body: JSON.stringify(data) }),
  removeAiConfig: () => request<void>("/ai-config", { method: "DELETE" }),
  aiSearch: (query: string) => request<AISearchResult>("/discovery/ai-search", { method: "POST", body: JSON.stringify({ query }) }),
};
