// Pure routing/classification for the multi-user (portal mode) /api gate in
// proxy.ts — kept separate so the exact bug this fixes (a new integration
// endpoint getting caught by the legacy "local-only" 410 guard) is testable
// with node --test, no Clerk/Next.js runtime required.

// Explicit multi-user API routes that are NOT proxied through
// /api/backend/... (which is always allowed — see isLegacyLocalOnlyApi).
const PORTAL_APIS = ["/api/backend", "/api/run", "/api/pipeline", "/api/status", "/api/whats-new", "/api/explore", "/api/explore/add", "/api/clis", "/api/version"];

// The Google OAuth callback (Phase 5) is reached by a top-level browser
// navigation FROM accounts.google.com, not a same-origin fetch() — the only
// /api route in this app that is deliberately reachable that way. Its
// security model is the server-validated one-time `state` value (see
// app.modules.integrations.service.consume_oauth_state), not Clerk auth or
// same-origin/Sec-Fetch-Site, so it alone is exempt from both the portal-API
// allowlist gate and the origin/CSRF guard.
export const OAUTH_CALLBACK_PATH = "/api/integrations/gmail/callback";

/** True for the one path that bypasses both the local-only-API gate and the
 *  origin/CSRF guard entirely — currently just the OAuth callback. */
export function isExemptFromPortalGating(pathname) {
  return pathname === OAUTH_CALLBACK_PATH;
}

/** True when `pathname` is an /api route that portal (multi-user) mode must
 *  refuse — a route from the single-user local dashboard's API surface
 *  (spawns processes, reads/writes the user's files) that has no business
 *  running against a shared multi-user backend. A NEW multi-user endpoint
 *  must be reachable either via /api/backend/... (the authenticated proxy
 *  to FastAPI) or explicitly listed in PORTAL_APIS/exempted here — never by
 *  weakening this check for everything else. */
export function isLegacyLocalOnlyApi(pathname) {
  if (!pathname.startsWith("/api/")) return false;
  if (isExemptFromPortalGating(pathname)) return false;
  return !PORTAL_APIS.includes(pathname) && !pathname.startsWith("/api/backend/");
}
