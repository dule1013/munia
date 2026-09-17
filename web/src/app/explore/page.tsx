import fs from "node:fs";
import { ExplorerView } from "@/components/explore/explorer-view";
import { careerOpsRoot, readApplications, readInbox } from "@/lib/career-ops";
import { seedExploreFilters } from "@/lib/core/portals";
import { DEFAULT_FILTERS } from "@/lib/explore";
import { serverApi } from "@/lib/api-server";
import type { CandidateJob, CandidateProfile } from "@/lib/api-client";
import { candidateJobsToLegacy } from "@/lib/portal-adapters";
import { portalMode } from "@/lib/portal-mode.mjs";

export const dynamic = "force-dynamic";

export default async function ExplorePage() {
  if (!portalMode()) {
    let seed = { filters: DEFAULT_FILTERS, seededFrom: [] as string[] };
    try { seed = seedExploreFilters(); } catch {}
    return <ExplorerView seed={seed} inboxSnapshot={readInbox()} appsSnapshot={readApplications()} rootExists={fs.existsSync(careerOpsRoot())} />;
  }
  const [candidate, items] = await Promise.all([serverApi<CandidateProfile>("/candidate/profile"), serverApi<CandidateJob[]>("/pipeline")]);
  const targetRoles = ((candidate.profile.target_roles || {}) as { primary?: unknown }).primary;
  const current = (candidate.profile.candidate || {}) as { location?: unknown };
  const filters = {
    ...DEFAULT_FILTERS,
    positive: Array.isArray(targetRoles) ? targetRoles.map(String) : [],
    allow: typeof current.location === "string" && current.location ? [current.location] : [],
  };
  const snapshot = candidateJobsToLegacy(items);
  return <ExplorerView seed={{ filters, seededFrom: ["candidate profile"] }} inboxSnapshot={snapshot.inbox} appsSnapshot={snapshot.applications} rootExists />;
}
