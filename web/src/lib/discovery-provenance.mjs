// Pure "Found via" label derivation for job discovery provenance (Phase 5
// Checkpoint E §7). Kept as a plain module (not inline in the .tsx) so it's
// testable with node --test with no build step, per web/AGENTS.md.

export const SOURCE_LABEL = {
  linkedin: "LinkedIn",
  greenhouse: "Greenhouse",
  lever: "Lever",
  ashby: "Ashby",
  workday: "Workday",
  icims: "iCIMS",
  "web-discovery": "Web Search",
};

/** For a single JobDiscovery {source, method}, the label to show in
 * "Found via: <label> · <label>". A watchlist-discovered job whose source
 * isn't one of the well-known ones above is labelled with its provider
 * name inline ("Company Watchlist (Teamtailor)") rather than just the raw
 * provider id, matching Phase 5's example. */
export function provenanceLabel(entry) {
  const source = SOURCE_LABEL[entry.source] ?? entry.source;
  if (entry.method === "company_watchlist" && !(entry.source in SOURCE_LABEL)) return `Company Watchlist (${source})`;
  return source;
}

/** Dedup labels across every discovery of one job, preserving first-seen order. */
export function provenanceLabels(entries) {
  const seen = new Set();
  const out = [];
  for (const entry of entries) {
    const label = provenanceLabel(entry);
    if (seen.has(label)) continue;
    seen.add(label);
    out.push(label);
  }
  return out;
}
