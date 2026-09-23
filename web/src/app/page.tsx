import { TodayDashboard } from "@/components/home/today-dashboard";
import { TodayView } from "@/components/home/today-view";
import { doctorState, pipelineSummary } from "@/lib/career-ops";
import { FirstRunHome } from "@/components/home/first-run-home";
import { OnboardingBanner } from "@/components/onboarding-banner";
import { portalMode } from "@/lib/portal-mode.mjs";

export const dynamic = "force-dynamic";

export default async function Home() {
  if (!portalMode()) {
    const state = doctorState();
    if (state.phase === "first-run") return <FirstRunHome />;
    const summary = pipelineSummary();
    return <>{state.onboardingNeeded && <OnboardingBanner />}<TodayDashboard applications={summary.applications} inbox={summary.inbox} inBetween={state.phase === "in-between"} /></>;
  }
  // Portal (multi-user) mode: cumulative, AI-qualified strong matches only
  // (Phase 5 follow-up §10) — GET /pipeline/today, fetched client-side by
  // TodayView so it can refresh without a full page reload.
  return <TodayView />;
}
