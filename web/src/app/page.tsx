import { TodayDashboard } from "@/components/home/today-dashboard";
import { doctorState, pipelineSummary } from "@/lib/career-ops";
import { FirstRunHome } from "@/components/home/first-run-home";
import { OnboardingBanner } from "@/components/onboarding-banner";
import { serverApi } from "@/lib/api-server";
import type { CandidateJob } from "@/lib/api-client";
import { candidateJobsToLegacy } from "@/lib/portal-adapters";
import { portalMode } from "@/lib/portal-mode.mjs";

export const dynamic = "force-dynamic";

export default async function Home() {
  if (!portalMode()) {
    const state = doctorState();
    if (state.phase === "first-run") return <FirstRunHome />;
    const summary = pipelineSummary();
    return <>{state.onboardingNeeded && <OnboardingBanner />}<TodayDashboard applications={summary.applications} inbox={summary.inbox} inBetween={state.phase === "in-between"} /></>;
  }
  const summary = candidateJobsToLegacy(await serverApi<CandidateJob[]>("/pipeline"));
  return <TodayDashboard applications={summary.applications} inbox={summary.inbox} inBetween={false} />;
}
