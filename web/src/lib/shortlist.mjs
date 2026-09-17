function bucketForHeading(heading) {
  if (/worth evaluating|worth a look|pass/i.test(heading)) return "worth";
  if (/uncertain|marginal|maybe/i.test(heading)) return "uncertain";
  return null;
}

export function parseAutomatedShortlist(markdown) {
  const result = new Map();
  let bucket = null;
  let current = null;
  const commit = () => {
    const url = current?.fields.get("direct application url") || current?.fields.get("url");
    if (!bucket || !current || !url) return;
    result.set(url, {
      bucket,
      company: current.company,
      role: current.role,
      location: current.fields.get("location") || "",
      posted: current.fields.get("posted") || "",
      source: current.fields.get("source") || "",
      eligibility: current.fields.get("eligibility") || "Uncertain",
      reason: current.fields.get("why it may fit") || current.fields.get("fit") || "",
    });
  };

  for (const line of String(markdown ?? "").split(/\r?\n/)) {
    const section = line.match(/^##\s+(.+)$/);
    if (section) {
      commit();
      current = null;
      bucket = bucketForHeading(section[1]);
      continue;
    }
    const item = line.match(/^###\s+(.+?)\s+[—-]\s+(.+)$/);
    if (item) {
      commit();
      current = { company: item[1].trim(), role: item[2].trim(), fields: new Map() };
      continue;
    }
    const field = line.match(/^[-*]\s+([^:]+):\s*(.+)$/);
    if (field && current) {
      current.fields.set(field[1].trim().toLowerCase(), field[2].trim());
      continue;
    }
    const compact = bucket && !current ? line.match(/^(.*),\s*(https?:\/\/[^,\s]+),\s*([^,]+),\s*(.+)$/) : null;
    if (compact) {
      const prefix = compact[1].split(/,\s*/).map((part) => part.trim()).filter(Boolean);
      if (prefix.length >= 5) {
        const company = prefix.shift();
        const source = prefix.pop();
        const posted = prefix.pop();
        const location = prefix.pop();
        result.set(compact[2], {
          bucket,
          company,
          role: prefix.join(", "),
          location,
          posted,
          source,
          eligibility: compact[3].trim(),
          reason: compact[4].trim(),
        });
      }
    }
  }
  commit();
  return result;
}

export function actionableUrlSet(inbox, shortlist) {
  const pending = (Array.isArray(inbox) ? inbox : []).filter((item) => !item.done && item.url);
  if (!(shortlist instanceof Map) || shortlist.size === 0) return new Set(pending.map((item) => item.url));
  return new Set(pending.filter((item) => shortlist.has(item.url)).map((item) => item.url));
}
