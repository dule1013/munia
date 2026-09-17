import type { Application, InboxJob } from "@/lib/career-ops";
import type { CandidateJob } from "@/lib/api-client";

export function candidateJobsToLegacy(items: CandidateJob[]): { inbox: InboxJob[]; applications: Application[] } {
  const inbox: InboxJob[] = [];
  const applications: Application[] = [];
  for (const item of items) {
    if (item.pipeline_status.toLowerCase() === "inbox" && !item.skipped) {
      inbox.push({
        candidateJobId: item.id,
        url: item.job.posting_url,
        company: item.job.company,
        role: item.job.title,
        location: item.job.location,
        done: false,
        postedAt: item.job.posted_at?.slice(0, 10) || item.job.first_seen_at.slice(0, 10),
        triageBucket: item.triage_result === "worth" ? "worth" : "uncertain",
        eligibility: item.eligibility || undefined,
        triageReason: item.triage_reason || undefined,
        scanSource: item.job.source,
      });
      continue;
    }
    applications.push({
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
    });
  }
  return { inbox, applications };
}
