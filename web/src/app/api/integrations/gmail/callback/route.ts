import type { NextRequest } from "next/server";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const API_URL = process.env.CAREER_OPS_API_URL || "http://127.0.0.1:8000";

// Deliberately UNAUTHENTICATED, and NOT routed through /api/backend's
// Clerk-gated forwarder (Phase 5 Checkpoint E §12): Google redirects the
// candidate's browser here directly after OAuth consent, carrying no Clerk
// bearer token. CSRF protection comes from FastAPI's own one-time `state`
// row (app.modules.integrations.service.consume_oauth_state), not from a
// Clerk session check on this hop.
//
// This is also the chosen callback architecture: GOOGLE_OAUTH_REDIRECT_URI
// points at Munia's ALREADY-PUBLIC web domain (this route), so no new DNS
// or public exposure of the FastAPI service is needed. The actual call to
// FastAPI happens server-side, over the existing private Railway network
// (CAREER_OPS_API_URL), exactly like every other backend call this app
// makes — only the inbound leg (Google -> browser -> here) is public, and
// that was already true of the whole web app.
export async function GET(req: NextRequest) {
  const upstream = new URL("/api/v1/integrations/gmail/callback", API_URL);
  upstream.search = req.nextUrl.search;
  const response = await fetch(upstream, { redirect: "manual", cache: "no-store" });
  const location = response.headers.get("location");
  if (response.status >= 300 && response.status < 400 && location) {
    return Response.redirect(location, 302);
  }
  return new Response(await response.text(), { status: response.status || 502 });
}
