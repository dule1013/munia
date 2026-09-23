"use client";

import { useEffect, useState } from "react";
import { Globe, Loader2, Newspaper, Radar } from "lucide-react";
import { Card } from "@/components/ui/card";
import { AIConfigPanel } from "@/components/discovery/ai-config-panel";
import { LinkedInPanel } from "@/components/discovery/linkedin-panel";
import { MorningStatusPanel } from "@/components/discovery/morning-status-panel";
import { WatchlistPanel } from "@/components/discovery/watchlist-panel";
import { portalApi, type SourceEntry, type SourceMetrics, type SourcesOverview as SourcesOverviewData } from "@/lib/api-client";

const METRIC_ORDER: (keyof SourceMetrics)[] = ["discovered", "eligible", "worth_evaluating", "applied"];
const METRIC_LABEL: Record<keyof SourceMetrics, string> = { discovered: "Discovered", eligible: "Eligible", worth_evaluating: "Worth evaluating", applied: "Applied" };

function MetricRow({ metrics }: { metrics?: SourceMetrics }) {
  if (!metrics) return null;
  return (
    <div className="mt-1 flex gap-3 text-xs text-faint">
      {METRIC_ORDER.map((key) => (
        <span key={key}>
          {METRIC_LABEL[key]} <span className="tabular-nums text-muted-foreground">{metrics[key]}</span>
        </span>
      ))}
    </div>
  );
}

function SourceRow({ source }: { source: SourceEntry }) {
  return (
    <li className="px-4 py-2.5">
      <div className="flex items-center gap-2">
        <span className="text-sm font-medium">{source.label}</span>
      </div>
      {source.metrics_available === false ? <p className="mt-1 text-xs text-faint">Detailed per-source metrics aren&apos;t available yet for this feed.</p> : <MetricRow metrics={source.metrics} />}
    </li>
  );
}

/** Replaces the old "Munia only scans 4 ATS networks" impression (Phase 5
 * §2) with the real, current discovery network — grouped, not a flat list
 * of the ~90 Career Ops provider modules that happen to exist. */
export function SourcesOverview() {
  const [data, setData] = useState<SourcesOverviewData | null>(null);

  useEffect(() => {
    portalApi
      .sourcesOverview()
      .then(setData)
      .catch(() => setData({ groups: [] }));
  }, []);

  if (!data) return <Loader2 className="size-5 animate-spin text-faint" />;

  const network = data.groups.find((g) => g.id === "network_scan");
  const watchlist = data.groups.find((g) => g.id === "company_watchlist");
  const feeds = data.groups.find((g) => g.id === "job_feed");
  const web = data.groups.find((g) => g.id === "web_discovery");

  return (
    <div className="space-y-6">
      <MorningStatusPanel />
      <LinkedInPanel />
      <WatchlistPanel />
      <AIConfigPanel />

      {network && (
        <Card>
          <div className="flex items-center gap-2">
            <Radar className="size-5 text-brand" />
            <h3 className="font-medium">{network.label}</h3>
          </div>
          <p className="mt-1 text-sm text-muted-foreground">Full public-network scans across these ATS platforms — no company list needed.</p>
          <ul className="mt-4 divide-y divide-border overflow-hidden rounded-2xl border border-border bg-surface/40">
            {network.sources?.map((s) => <SourceRow key={s.id} source={s} />)}
          </ul>
        </Card>
      )}

      {feeds && (
        <Card>
          <div className="flex items-center gap-2">
            <Newspaper className="size-5 text-brand" />
            <h3 className="font-medium">{feeds.label}</h3>
          </div>
          <p className="mt-1 text-sm text-muted-foreground">Low-cost, curated feeds. Kept small deliberately — see Discovery Sources for why.</p>
          <ul className="mt-4 divide-y divide-border overflow-hidden rounded-2xl border border-border bg-surface/40">
            {feeds.sources?.map((s) => <SourceRow key={s.id} source={s} />)}
          </ul>
        </Card>
      )}

      {web && (
        <Card>
          <div className="flex items-center gap-2">
            <Globe className="size-5 text-brand" />
            <h3 className="font-medium">{web.label}</h3>
          </div>
          <p className="mt-1 text-sm text-muted-foreground">AI-assisted web search for roles the structured scanners can&apos;t reach directly. Runs less often — it costs tokens.</p>
          <ul className="mt-4 divide-y divide-border overflow-hidden rounded-2xl border border-border bg-surface/40">
            {web.sources?.map((s) => <SourceRow key={s.id} source={s} />)}
          </ul>
        </Card>
      )}

      {watchlist?.summary && (
        <p className="text-xs text-faint">
          Company Watchlist: {watchlist.summary.companies_watched} companies watched
          {watchlist.summary.errors > 0 ? ` · ${watchlist.summary.errors} with scan errors` : ""}.
        </p>
      )}
    </div>
  );
}
