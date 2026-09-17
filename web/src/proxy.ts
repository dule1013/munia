import { clerkMiddleware } from "@clerk/nextjs/server";
import { NextResponse } from "next/server";
import { checkRequest, parseAllowedHosts } from "@/lib/origin-guard.mjs";
import { portalMode } from "@/lib/portal-mode.mjs";

const publicPaths = ["/sign-in", "/sign-up"];
const portalApis = ["/api/backend", "/api/run", "/api/pipeline", "/api/status", "/api/whats-new", "/api/explore", "/api/explore/add", "/api/clis", "/api/version"];

export const proxy = clerkMiddleware(async (auth, req) => {
  const pathname = req.nextUrl.pathname;
  let multiUser: boolean;
  try {
    multiUser = portalMode();
  } catch {
    return NextResponse.json({ error: "Invalid portal mode configuration." }, { status: 503 });
  }
  if (!multiUser) {
    if (!pathname.startsWith("/api/")) return NextResponse.next();
    const decision = checkRequest({ secFetchSite: req.headers.get("sec-fetch-site"), origin: req.headers.get("origin"), host: req.headers.get("host"), allowedHosts: parseAllowedHosts(process.env.CAREER_OPS_WEB_ALLOWED_HOSTS) });
    return decision.ok ? NextResponse.next() : NextResponse.json({ error: decision.reason }, { status: decision.status });
  }
  const isPublic = publicPaths.some((path) => pathname === path || pathname.startsWith(`${path}/`));
  if (!isPublic) await auth.protect();
  if (pathname.startsWith("/api/") && !portalApis.includes(pathname) && !pathname.startsWith("/api/backend/")) {
    return NextResponse.json({ error: "This local-only endpoint is disabled in multi-user mode." }, { status: 410 });
  }
  if (pathname.startsWith("/api/")) {
    const decision = checkRequest({
      secFetchSite: req.headers.get("sec-fetch-site"),
      origin: req.headers.get("origin"),
      host: req.headers.get("host"),
      allowedHosts: parseAllowedHosts(process.env.CAREER_OPS_WEB_ALLOWED_HOSTS),
    });
    if (!decision.ok) return NextResponse.json({ error: decision.reason }, { status: decision.status });
  }
  return NextResponse.next();
});

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico|.*\\.(?:svg|png|jpg|jpeg|gif|webp|ico)$).*)"],
};
