import { serverApi } from "@/lib/api-server";
import type { CandidateJob } from "@/lib/api-client";
import { candidateJobsToLegacy } from "@/lib/portal-adapters";
import { pipelineSummary } from "@/lib/career-ops";
import { portalMode } from "@/lib/portal-mode.mjs";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET() {
  if (!portalMode()) return Response.json(pipelineSummary());
  const summary = candidateJobsToLegacy(await serverApi<CandidateJob[]>("/pipeline"));
  return Response.json({ ...summary, root: null, rootExists: true });
}
