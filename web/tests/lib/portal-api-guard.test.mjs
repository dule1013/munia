import { test } from "node:test";
import assert from "node:assert/strict";
import { OAUTH_CALLBACK_PATH, isExemptFromPortalGating, isLegacyLocalOnlyApi } from "../../src/lib/portal-api-guard.mjs";

// Reproduces the exact production bug: clicking "Connect Gmail" completed
// fine (POST /api/backend/integrations/gmail/connect, itself proxied and
// Clerk-authenticated), but Google's redirect back to
// /api/integrations/gmail/callback was answered with
// {"error": "This local-only endpoint is disabled in multi-user mode."}
// (410) — because that path matched neither /api/backend/... nor the
// portalApis allowlist.
test("regression: the OAuth callback must NOT be classified as a legacy local-only API", () => {
  assert.equal(isLegacyLocalOnlyApi(OAUTH_CALLBACK_PATH), false);
  assert.equal(isExemptFromPortalGating(OAUTH_CALLBACK_PATH), true);
});

test("the OAuth callback path is exactly /api/integrations/gmail/callback", () => {
  assert.equal(OAUTH_CALLBACK_PATH, "/api/integrations/gmail/callback");
});

test("a future path under /api/integrations/ that ISN'T the callback is still gated normally", () => {
  // Guards against accidentally widening the exemption to a whole prefix —
  // only the exact callback path is exempt.
  assert.equal(isExemptFromPortalGating("/api/integrations/gmail/status"), false);
  assert.equal(isLegacyLocalOnlyApi("/api/integrations/gmail/status"), true);
});

test("/connect /status /sync /disconnect go through the authenticated backend proxy and are already allowed", () => {
  for (const path of ["/api/backend/integrations/gmail/connect", "/api/backend/integrations/gmail/status", "/api/backend/integrations/gmail/sync", "/api/backend/integrations/gmail/disconnect"]) {
    assert.equal(isLegacyLocalOnlyApi(path), false, path);
  }
});

test("the existing portalApis allowlist is unaffected (general protection not weakened)", () => {
  for (const path of ["/api/run", "/api/pipeline", "/api/status", "/api/whats-new", "/api/explore", "/api/explore/add", "/api/clis", "/api/version"]) {
    assert.equal(isLegacyLocalOnlyApi(path), false, path);
  }
});

test("a genuine legacy local-only endpoint is still blocked (general protection not weakened)", () => {
  assert.equal(isLegacyLocalOnlyApi("/api/portals/verify"), true);
  assert.equal(isLegacyLocalOnlyApi("/api/cv-pdf"), true);
});

test("non-/api paths are never classified as a local-only API", () => {
  assert.equal(isLegacyLocalOnlyApi("/discovery"), false);
  assert.equal(isLegacyLocalOnlyApi("/"), false);
});
