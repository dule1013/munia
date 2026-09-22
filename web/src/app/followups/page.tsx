import { Suspense } from "react";
import { FollowupsView } from "@/components/followups/followups-view";
import { portalMode } from "@/lib/portal-mode.mjs";

export const dynamic = "force-dynamic"; // cadence is computed fresh per request

export default function FollowupsPage() {
  if (portalMode()) {
    return (
      <div className="mx-auto w-full max-w-[120rem] px-6 py-8 lg:px-8">
        <h1 className="font-display text-2xl tracking-tight text-landing">Follow-ups</h1>
        <p className="mt-6 max-w-xl rounded-xl border border-dashed border-border bg-surface/30 p-4 text-sm text-muted">
          Follow-ups are unavailable in multi-user mode for now.
        </p>
      </div>
    );
  }
  return (
    <Suspense>
      <FollowupsView />
    </Suspense>
  );
}
