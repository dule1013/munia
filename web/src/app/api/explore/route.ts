import { serverApi } from "@/lib/api-server";
import { runDiscovery } from "@/lib/core/scan";
import { DEFAULT_FILTERS, parseExplorePatch, type DiscoveredOffer, type ScanEvent } from "@/lib/explore";
import { portalMode } from "@/lib/portal-mode.mjs";

export const runtime = "nodejs";
export const maxDuration = 300;
export const dynamic = "force-dynamic";

export async function POST(req: Request) {
  const body = await req.json().catch(() => ({})) as { since?: number; sinceDays?: number; ats?: string[]; limit?: number; limitPerAts?: number };
  if (!portalMode()) {
    const filters = parseExplorePatch(body, DEFAULT_FILTERS);
    const encoder = new TextEncoder();
    return new Response(new ReadableStream({ async start(controller) {
      const send = (event: ScanEvent) => controller.enqueue(encoder.encode(JSON.stringify(event) + "\n"));
      send({ kind: "start", ats: filters.ats, sinceDays: filters.sinceDays, limit: filters.limitPerAts, free: true });
      let offers: DiscoveredOffer[] = [];
      try { offers = await runDiscovery(filters, send); } catch (error) { send({ kind: "error", message: error instanceof Error ? error.message : "discovery failed" }); }
      send({ kind: "done", count: offers.length, offers, cost: { tokens: 0, usd: 0 } });
      controller.close();
    } }), { headers: { "Content-Type": "application/x-ndjson; charset=utf-8", "Cache-Control": "no-cache, no-transform" } });
  }
  // Share the local path's parser so the hosted request is clamped/cleaned the
  // same way (limitPerAts bounds, sinceDays window, ATS allowlist).
  const hosted = parseExplorePatch(body, DEFAULT_FILTERS);
  const request = { since_days: hosted.sinceDays, ats: hosted.ats, limit_per_ats: hosted.limitPerAts };
  try {
    const run = await serverApi<{ id: string }>("/discovery/runs", { method: "POST", body: JSON.stringify(request) });
    return Response.json({ runId: run.id }, { status: 202 });
  } catch (error) {
    return Response.json({ error: error instanceof Error ? error.message : "discovery failed" }, { status: 502 });
  }
}
