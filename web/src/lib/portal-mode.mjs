export function parsePortalMode(value) {
  const normalized = String(value ?? "").trim().toLowerCase();
  if (!normalized || normalized === "false") return false;
  if (normalized === "true") return true;
  throw new Error('CAREER_OPS_MULTI_USER must be exactly "true" or "false"');
}

export function portalMode(env = process.env) {
  return parsePortalMode(env.CAREER_OPS_MULTI_USER);
}
