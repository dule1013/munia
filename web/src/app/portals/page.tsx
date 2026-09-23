import { Radar } from "lucide-react";
import { PortalsView } from "@/components/portals-view";
import { portalMode } from "@/lib/portal-mode.mjs";

export const dynamic = "force-dynamic";

export default function PortalsPage() {
  const portalEnabled = portalMode();
  return (
    <div className="mx-auto w-full max-w-[120rem] px-6 py-8 lg:px-8">
      <div className="flex items-center gap-3">
        <Radar className="size-6 text-brand" />
        <h1 className="font-display text-2xl tracking-tight text-landing">Portals</h1>
      </div>
      {portalEnabled ? (
        <p className="mt-6 max-w-xl rounded-xl border border-dashed border-border bg-surface/30 p-4 text-sm text-muted-foreground">
          Portal verification is unavailable in multi-user mode. Discovery uses the shared backend scanner instead.
        </p>
      ) : (
        <>
          <p className="mt-1.5 max-w-xl text-sm text-muted-foreground">
            The companies career-ops watches for new roles. Run a health check to catch company boards that have quietly
            broken — a broken link means that company silently disappears from every future scan.
          </p>
          <p className="mt-1.5 text-xs text-faint">
            Backed by <code className="text-muted-foreground">portals.yml</code> — edit it directly or ask the assistant.
          </p>
          <div className="mt-6">
            <PortalsView />
          </div>
        </>
      )}
    </div>
  );
}
