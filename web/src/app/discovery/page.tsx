import { Radar } from "lucide-react";
import { SourcesOverview } from "@/components/discovery/sources-overview";
import { portalMode } from "@/lib/portal-mode.mjs";

export const dynamic = "force-dynamic";

export default function DiscoveryPage() {
  const portalEnabled = portalMode();
  return (
    <div className="mx-auto w-full max-w-[120rem] px-6 py-8 lg:px-8">
      <div className="flex items-center gap-3">
        <Radar className="size-6 text-brand" />
        <h1 className="font-display text-2xl tracking-tight text-landing">Discovery</h1>
      </div>
      <p className="mt-1.5 max-w-2xl text-sm text-muted-foreground">Every way Munia finds you jobs — LinkedIn Job Alerts, the companies you watch directly, network-wide ATS scans, curated feeds, and AI web search.</p>
      {portalEnabled ? (
        <div className="mt-6">
          <SourcesOverview />
        </div>
      ) : (
        <p className="mt-6 max-w-xl rounded-xl border border-dashed border-border bg-surface/30 p-4 text-sm text-muted-foreground">
          The Discovery sources view is available in multi-user (portal) mode. In local mode, edit <code className="text-foreground">portals.yml</code> directly or use the <code className="text-foreground">/explore</code> page.
        </p>
      )}
    </div>
  );
}
