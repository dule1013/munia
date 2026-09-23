"use client";

import { useEffect, useState } from "react";
import { CheckCircle2, CircleAlert, CircleX } from "lucide-react";
import { Card } from "@/components/ui/card";
import { portalApi, type MorningStatus } from "@/lib/api-client";

const SOURCE_LABEL: Record<string, string> = { linkedin: "LinkedIn", watchlist: "Watchlist", greenhouse: "Greenhouse", lever: "Lever", ashby: "Ashby", workday: "Workday", icims: "iCIMS" };

function SourceIcon({ status }: { status: string }) {
  if (status === "error") return <CircleX className="size-3.5 text-red-500" />;
  if (status === "ok") return <CheckCircle2 className="size-3.5 text-emerald-500" />;
  return <CircleAlert className="size-3.5 text-amber-500" />;
}

/** Operational visibility for the shared morning cycle (Phase 5 follow-up
 * §11) — lives on Discovery, not Today, and stays out of the way: just the
 * last run's timestamp/outcome and a per-source checklist. */
export function MorningStatusPanel() {
  const [status, setStatus] = useState<MorningStatus | null>(null);

  useEffect(() => {
    portalApi.morningStatus().then(setStatus).catch(() => setStatus(null));
  }, []);

  if (!status || status.status === "never_run") return null;

  return (
    <Card>
      <h3 className="font-medium">Last morning search</h3>
      <p className="mt-1 text-sm text-muted-foreground">
        {status.finished_at ? new Date(status.finished_at).toLocaleString() : "in progress"} — {status.status === "completed" ? "Completed" : status.status === "completed_with_warnings" ? "Completed with warnings" : status.status === "failed" ? "Failed" : "Running"}
      </p>
      {Object.keys(status.sources).length > 0 && (
        <ul className="mt-3 flex flex-wrap gap-x-4 gap-y-1.5">
          {Object.entries(status.sources).map(([source, sourceStatus]) => (
            <li key={source} className="flex items-center gap-1.5 text-sm text-muted-foreground">
              <SourceIcon status={sourceStatus} /> {SOURCE_LABEL[source] || source}
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
