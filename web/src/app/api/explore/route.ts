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
  const request = { since_days: body.sinceDays || body.since || 7, ats: body.ats, limit_per_ats: body.limitPerAts || body.limit || 150 };
  const result = await serverApi<{ offers?: unknown[]; companiesScanned?: number; unreachableBoards?: number }>("/discovery/reverse-ats", { method: "POST", body: JSON.stringify(request) });
  const offers = Array.isArray(result.offers) ? result.offers : [];
  const events = [
    { kind: "start", ats: request.ats, sinceDays: request.since_days, limit: request.limit_per_ats, free: true },
    { kind: "summary", companiesScanned: result.companiesScanned || 0, unreachable: result.unreachableBoards || 0, matches: offers.length },
    { kind: "done", count: offers.length, offers, cost: { tokens: 0, usd: 0 } },
  ];
  return new Response(events.map((event) => JSON.stringify(event)).join("\n") + "\n", { headers: { "Content-Type": "application/x-ndjson; charset=utf-8", "Cache-Control": "no-cache, no-transform" } });
}
