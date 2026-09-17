import { serverApi } from "@/lib/api-server";
import type { CandidateJob } from "@/lib/api-client";
import { pipelineSummary } from "@/lib/career-ops";
import { portalMode } from "@/lib/portal-mode.mjs";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET() {
  if (!portalMode()) {
    const offers = pipelineSummary().inbox.filter((item) => !item.done && item.triageBucket !== undefined).map((item) => ({ company: item.company, title: item.role, location: item.location || "", postedAt: item.postedAt || "", source: item.scanSource || "pipeline", ats: item.scanSource || "pipeline", url: item.url }));
    return Response.json({ count: offers.length, offers });
  }
  const items = await serverApi<CandidateJob[]>("/pipeline");
  const actionable = items.filter((item) => item.pipeline_status.toLowerCase() === "inbox" && !item.skipped && item.triage_result !== "discard");
  const offers = actionable.map((item) => ({ company: item.job.company, title: item.job.title, location: item.job.location, postedAt: item.job.posted_at?.slice(0, 10) || item.job.first_seen_at.slice(0, 10), ats: item.job.source, source: item.job.source, url: item.job.posting_url }));
  return Response.json({ count: offers.length, offers, rawCount: items.length });
}
