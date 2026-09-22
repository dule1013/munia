import { test } from "node:test";
import assert from "node:assert/strict";
import { provenanceLabel, provenanceLabels } from "../../src/lib/discovery-provenance.mjs";

test("known ATS source maps to its display label", () => {
  assert.equal(provenanceLabel({ source: "greenhouse", method: "reverse_ats" }), "Greenhouse");
  assert.equal(provenanceLabel({ source: "linkedin", method: "email_alert" }), "LinkedIn");
});

test("watchlist discovery through an unlisted provider names the provider", () => {
  assert.equal(provenanceLabel({ source: "teamtailor", method: "company_watchlist" }), "Company Watchlist (teamtailor)");
});

test("watchlist discovery through a well-known provider just shows the provider", () => {
  assert.equal(provenanceLabel({ source: "greenhouse", method: "company_watchlist" }), "Greenhouse");
});

test("provenanceLabels dedupes while preserving first-seen order", () => {
  const entries = [
    { source: "linkedin", method: "email_alert" },
    { source: "greenhouse", method: "reverse_ats" },
    { source: "linkedin", method: "email_alert" },
  ];
  assert.deepEqual(provenanceLabels(entries), ["LinkedIn", "Greenhouse"]);
});

test("empty discovery list yields no labels", () => {
  assert.deepEqual(provenanceLabels([]), []);
});
