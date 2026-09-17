import { Suspense } from "react";
import { PipelineView } from "@/components/pipeline-view";
import { pipelineSummary } from "@/lib/career-ops";
import { serverApi } from "@/lib/api-server";
import type { CandidateJob } from "@/lib/api-client";
import { candidateJobsToLegacy } from "@/lib/portal-adapters";
import { portalMode } from "@/lib/portal-mode.mjs";

export const dynamic = "force-dynamic";

export default async function PipelinePage() {
  const summary = portalMode() ? candidateJobsToLegacy(await serverApi<CandidateJob[]>("/pipeline")) : pipelineSummary();
  return <Suspense><PipelineView applications={summary.applications} inbox={summary.inbox} /></Suspense>;
}
