"use client";

import { useEffect, useState } from "react";
import { Loader2, Mail, RefreshCw, Unplug } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { portalApi, type IntegrationStatus } from "@/lib/api-client";

const STATUS_TONE: Record<string, "good" | "warn" | "bad" | "info" | "muted"> = {
  connected: "good",
  disconnected: "muted",
  error: "bad",
  revoked: "bad",
};

const STATUS_LABEL: Record<string, string> = {
  connected: "Connected",
  disconnected: "Not connected",
  error: "Error",
  revoked: "Needs reconnect",
};

/** LinkedIn Job Alert ingestion UX (Phase 5 Checkpoint C/E). Degrades to a
 * plain "not configured" state without crashing when Google OAuth hasn't
 * been set up on this deployment yet (§4/§11) — every request below fails
 * safely (503/409) and is surfaced as text, never thrown at the page. */
export function LinkedInPanel() {
  const [status, setStatus] = useState<IntegrationStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [notConfigured, setNotConfigured] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  const load = () => {
    setLoading(true);
    portalApi
      .gmailStatus()
      .then(setStatus)
      .catch(() => setStatus(null))
      .finally(() => setLoading(false));
  };

  useEffect(load, []);

  async function connect() {
    setBusy(true);
    setMessage(null);
    try {
      const { authorization_url } = await portalApi.gmailConnect();
      window.location.href = authorization_url;
    } catch {
      setNotConfigured(true);
    } finally {
      setBusy(false);
    }
  }

  async function disconnect() {
    setBusy(true);
    try {
      await portalApi.gmailDisconnect();
      load();
    } finally {
      setBusy(false);
    }
  }

  async function syncNow() {
    setBusy(true);
    setMessage(null);
    try {
      const result = await portalApi.gmailSyncNow();
      setMessage(result.status === "ok" ? `Synced — ${result.jobs_found} job${result.jobs_found === 1 ? "" : "s"} found, ${result.jobs_created} new.` : `Sync failed: ${result.error ?? "unknown error"}`);
      load();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Sync failed.");
    } finally {
      setBusy(false);
    }
  }

  const state = status?.status ?? "disconnected";

  return (
    <Card>
      <div className="flex items-start gap-3">
        <Mail className="mt-0.5 size-5 text-brand" />
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <h3 className="font-medium">LinkedIn Job Alerts</h3>
            {!loading && <Badge tone={STATUS_TONE[state] ?? "muted"}>{STATUS_LABEL[state] ?? state}</Badge>}
          </div>
          <p className="mt-1 text-sm text-muted-foreground">
            Munia reads LinkedIn Job Alert emails from your Gmail to discover jobs. It does not log into or scrape LinkedIn, and never sees anything else in your inbox.
          </p>

          {loading ? (
            <Loader2 className="mt-3 size-4 animate-spin text-faint" />
          ) : notConfigured ? (
            <p className="mt-3 rounded-xl border border-dashed border-border bg-surface/30 p-3 text-sm text-muted-foreground">Gmail integration isn&apos;t configured on this deployment yet.</p>
          ) : state === "disconnected" ? (
            <Button className="mt-3" onClick={connect} disabled={busy}>
              Connect Gmail
            </Button>
          ) : (
            <div className="mt-3 space-y-2">
              {status?.account_email && <p className="text-sm text-muted-foreground">Account: {status.account_email}</p>}
              <p className="text-sm text-muted-foreground">Last sync: {status?.last_sync_at ? new Date(status.last_sync_at).toLocaleString() : "never"}</p>
              {(state === "error" || state === "revoked") && status?.last_error && <p className="text-sm text-red-600 dark:text-red-400">{status.last_error}</p>}
              <div className="flex flex-wrap gap-2 pt-1">
                {(state === "error" || state === "revoked") && (
                  <Button onClick={connect} disabled={busy}>
                    Reconnect Gmail
                  </Button>
                )}
                {state === "connected" && (
                  <Button variant="outline" onClick={syncNow} disabled={busy}>
                    <RefreshCw className="size-4" /> Sync now
                  </Button>
                )}
                <Button variant="ghost" onClick={disconnect} disabled={busy}>
                  <Unplug className="size-4" /> Disconnect
                </Button>
              </div>
              {message && <p className="text-sm text-muted-foreground">{message}</p>}
            </div>
          )}
        </div>
      </div>
    </Card>
  );
}
