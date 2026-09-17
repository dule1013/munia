import assert from "node:assert/strict";
import { test } from "node:test";
import { actionableUrlSet, parseAutomatedShortlist } from "../../src/lib/shortlist.mjs";

test("parseAutomatedShortlist maps triage metadata by direct URL", () => {
  const md = `# Morning Shortlist

## Worth evaluating

### Super — Senior Engineering Manager

- Location: Spain
- Posted: 2026-09-14 (1 day old)
- Source: Greenhouse direct company board
- Direct application URL: https://jobs.example/super
- Eligibility: Confirmed for Spain
- Why it may fit: Leads two engineering squads.

## Uncertain

No uncertain opportunities remain today.
`;
  const result = parseAutomatedShortlist(md);
  assert.deepEqual(result.get("https://jobs.example/super"), {
    bucket: "worth",
    company: "Super",
    role: "Senior Engineering Manager",
    location: "Spain",
    posted: "2026-09-14 (1 day old)",
    source: "Greenhouse direct company board",
    eligibility: "Confirmed for Spain",
    reason: "Leads two engineering squads.",
  });
});

test("parseAutomatedShortlist accepts the compact scheduled-agent row", () => {
  const md = `## Worth evaluating for PASS

Super, Senior Engineering Manager, Spain, 1 day old (2026-09-14), greenhouse-api, https://jobs.example/super, Authorized, Multi-squad leadership scope.

## Uncertain for every MARGINAL

(none)
`;
  assert.deepEqual(parseAutomatedShortlist(md).get("https://jobs.example/super"), {
    bucket: "worth",
    company: "Super",
    role: "Senior Engineering Manager",
    location: "Spain",
    posted: "1 day old (2026-09-14)",
    source: "greenhouse-api",
    eligibility: "Authorized",
    reason: "Multi-squad leadership scope.",
  });
});

test("actionableUrlSet keeps only pending URLs represented by automated triage", () => {
  const shortlist = new Map([
    ["https://jobs.example/keep", { bucket: "worth" }],
    ["https://jobs.example/uncertain", { bucket: "uncertain" }],
  ]);
  const inbox = [
    { url: "https://jobs.example/keep", done: false },
    { url: "https://jobs.example/uncertain", done: false },
    { url: "https://jobs.example/raw", done: false },
    { url: "https://jobs.example/done", done: true },
  ];
  assert.deepEqual([...actionableUrlSet(inbox, shortlist)].sort(), [
    "https://jobs.example/keep",
    "https://jobs.example/uncertain",
  ]);
});
