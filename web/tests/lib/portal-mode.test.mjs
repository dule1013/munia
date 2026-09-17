import test from "node:test";
import assert from "node:assert/strict";
import { parsePortalMode, portalMode } from "../../src/lib/portal-mode.mjs";

test("portal mode has one server-owned environment source", () => {
  assert.equal(portalMode({}), false);
  assert.equal(portalMode({ CAREER_OPS_MULTI_USER: "false", NEXT_PUBLIC_CAREER_OPS_MULTI_USER: "true" }), false);
  assert.equal(portalMode({ CAREER_OPS_MULTI_USER: "true", NEXT_PUBLIC_CAREER_OPS_MULTI_USER: "false" }), true);
});

test("invalid portal mode fails closed instead of selecting local files", () => {
  assert.throws(() => parsePortalMode("yes"), /must be exactly/);
  assert.throws(() => parsePortalMode("1"), /must be exactly/);
});
