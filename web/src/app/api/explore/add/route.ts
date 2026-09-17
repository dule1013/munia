import { serverApi } from "@/lib/api-server";
import type { DiscoveredOffer } from "@/lib/explore";
import { addOffersToPipeline } from "@/lib/core/pipeline";
import { portalMode } from "@/lib/portal-mode.mjs";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function POST(req: Request) {
  const body = await req.json().catch(() => null) as { offers?: DiscoveredOffer[] } | null;
  if (!body?.offers?.length) return Response.json({ added: 0 });
  if (!portalMode()) return Response.json(await addOffersToPipeline(body.offers));
  return Response.json(await serverApi("/discovery/offers", { method: "POST", body: JSON.stringify({ offers: body.offers }) }));
}
