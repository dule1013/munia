"use client";

import { useEffect, useState } from "react";
import { Building2, Loader2, Plus, Trash2 } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { portalApi, type WatchedCompany } from "@/lib/api-client";

const SCAN_STATUS_TONE: Record<string, "good" | "warn" | "bad" | "info" | "muted"> = {
  ok: "good",
  error: "bad",
  unsupported_provider: "warn",
  never_scanned: "muted",
};

const SCAN_STATUS_LABEL: Record<string, string> = {
  ok: "Scanning fine",
  error: "Scan error",
  unsupported_provider: "Not scannable yet",
  never_scanned: "Not scanned yet",
};

/** Company Watchlist CRUD (Phase 5 Checkpoint B/D/E). Provider detection is
 * automatic — the candidate only ever enters a name + careers URL, never an
 * ATS name. If Munia can't detect a supported provider, that's said plainly
 * instead of silently accepting a company that will never actually scan. */
export function WatchlistPanel() {
  const [companies, setCompanies] = useState<WatchedCompany[] | null>(null);
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = () => {
    portalApi
      .watchlist()
      .then(setCompanies)
      .catch(() => setCompanies([]));
  };

  useEffect(load, []);

  async function addCompany(event: React.FormEvent) {
    event.preventDefault();
    if (!name.trim()) return;
    setBusy(true);
    setError(null);
    try {
      await portalApi.addWatchedCompany({ company_name: name.trim(), careers_url: url.trim() || null });
      setName("");
      setUrl("");
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not add company.");
    } finally {
      setBusy(false);
    }
  }

  async function toggleEnabled(company: WatchedCompany) {
    setBusy(true);
    try {
      await portalApi.updateWatchedCompany(company.id, { enabled: !company.enabled });
      load();
    } finally {
      setBusy(false);
    }
  }

  async function remove(company: WatchedCompany) {
    setBusy(true);
    try {
      await portalApi.removeWatchedCompany(company.id);
      load();
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card>
      <div className="flex items-center gap-2">
        <Building2 className="size-5 text-brand" />
        <h3 className="font-medium">Company Watchlist</h3>
      </div>
      <p className="mt-1 text-sm text-muted">Watch a specific company&apos;s careers page. Munia detects the right way to scan it automatically.</p>

      <form onSubmit={addCompany} className="mt-4 flex flex-wrap items-end gap-2">
        <div className="flex-1 min-w-[10rem]">
          <label className="text-xs text-faint">Company name</label>
          <input value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Docplanner" className="mt-1 w-full rounded-md border border-border bg-surface px-3 py-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-brand/50" />
        </div>
        <div className="flex-1 min-w-[14rem]">
          <label className="text-xs text-faint">Careers URL</label>
          <input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://jobs.example.com/company" className="mt-1 w-full rounded-md border border-border bg-surface px-3 py-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-brand/50" />
        </div>
        <Button type="submit" disabled={busy || !name.trim()}>
          <Plus className="size-4" /> Add
        </Button>
      </form>
      {error && <p className="mt-2 text-sm text-red-600 dark:text-red-400">{error}</p>}

      {companies === null ? (
        <Loader2 className="mt-4 size-4 animate-spin text-faint" />
      ) : companies.length === 0 ? (
        <p className="mt-4 text-sm text-faint">No companies watched yet.</p>
      ) : (
        <ul className="mt-4 divide-y divide-border overflow-hidden rounded-2xl border border-border bg-surface/40">
          {companies.map((company) => (
            <li key={company.id} className="flex flex-wrap items-center gap-3 px-4 py-2.5">
              <span className="shrink-0 text-sm font-medium">{company.company_name}</span>
              {company.careers_url && <span className="truncate font-mono text-xs text-faint">{company.careers_url}</span>}
              <div className="ml-auto flex shrink-0 items-center gap-2">
                {company.provider ? (
                  <Badge tone="info">{company.provider}</Badge>
                ) : (
                  <Badge tone="warn">Munia can&apos;t automatically scan this careers page yet</Badge>
                )}
                <Badge tone={SCAN_STATUS_TONE[company.scan_status ?? "never_scanned"] ?? "muted"}>{SCAN_STATUS_LABEL[company.scan_status ?? "never_scanned"] ?? company.scan_status}</Badge>
                <button onClick={() => toggleEnabled(company)} disabled={busy} className="text-xs text-muted underline-offset-2 hover:underline">
                  {company.enabled ? "Disable" : "Enable"}
                </button>
                <button onClick={() => remove(company)} disabled={busy} className="text-muted hover:text-red-600 dark:hover:text-red-400">
                  <Trash2 className="size-4" />
                </button>
              </div>
              {company.scan_status === "error" && company.last_scan_error && <p className="w-full text-xs text-red-600 dark:text-red-400">{company.last_scan_error}</p>}
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
