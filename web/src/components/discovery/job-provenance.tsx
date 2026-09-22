"use client";

import { useEffect, useState } from "react";
import { portalApi, type JobDiscoveryEntry } from "@/lib/api-client";
import { provenanceLabels } from "@/lib/discovery-provenance.mjs";

/** "Found via: LinkedIn · Greenhouse" — job provenance without exposing
 * duplicate jobs or which candidate's mailbox/watchlist found it (Phase 5
 * Checkpoint E §7/§10). One canonical Job, many discovery observations. */
export function JobProvenance({ jobId }: { jobId: string }) {
  const [entries, setEntries] = useState<JobDiscoveryEntry[] | null>(null);

  useEffect(() => {
    portalApi
      .jobDiscoveries(jobId)
      .then(setEntries)
      .catch(() => setEntries([]));
  }, [jobId]);

  if (!entries || entries.length === 0) return null;

  return (
    <p className="text-xs text-faint">
      Found via: <span className="text-muted">{provenanceLabels(entries).join(" · ")}</span>
    </p>
  );
}
