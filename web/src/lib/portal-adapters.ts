import type { Application, InboxJob } from "@/lib/career-ops";
import type { CandidateJob } from "@/lib/api-client";

export function candidateJobsToLegacy(items: CandidateJob[]): { inbox: InboxJob[]; applications: Application[] } {
  const inbox: InboxJob[] = [];
  const applications: Application[] = [];
  for (const item of items) {
    // A location-ineligible job is functionally discarded by the backend's
    // own location gate (apply_location_eligibility) even though its
    // pipeline_status stays "Inbox" — GET /pipeline/inbox (the properly
    // filtered endpoint) excludes it, but PipelinePage's "ALL"/other-tabs
    // view is built from the raw, unfiltered GET /pipeline response, so it
    // must exclude the same rows here to avoid the geographically
    // incompatible jobs the location gate was built to remove from
    // reappearing in the one Inbox list a candidate actually looks at.
    if (item.pipeline_status.toLowerCase() === "inbox" && !item.skipped && item.eligibility === "ineligible") {
      applications.push({
        n: item.id,
        date: item.job.first_seen_at.slice(0, 10),
        company: item.job.company,
        via: "",
        role: item.job.title,
        score: "",
        status: "Discarded",
        pdf: "",
        report: "",
        notes: item.triage_reason || "Location incompatible",
      });
      continue;
    }
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
