"use client";

import { useEffect, useState } from "react";
import { Loader2, Sparkles } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { portalApi, type AIConfigStatus } from "@/lib/api-client";

/** Candidate-specific AI configuration (Phase 5 follow-up §9). Munia has no
 * shared/global AI credential — each candidate brings their own Anthropic
 * key, encrypted server-side and scoped to them alone. Used for AI Search
 * and (once approved) automated morning job matching. */
export function AIConfigPanel() {
  const [status, setStatus] = useState<AIConfigStatus | null>(null);
  const [model, setModel] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  const load = () => {
    portalApi
      .aiConfigStatus()
      .then((s) => {
        setStatus(s);
        setModel(s.model || s.available_models[0]?.id || "");
      })
      .catch(() => setStatus(null));
  };

  useEffect(load, []);

  async function save(event: React.FormEvent) {
    event.preventDefault();
    if (!apiKey.trim() || !model) return;
    setBusy(true);
    setMessage(null);
    try {
      await portalApi.setAiConfig({ model, api_key: apiKey.trim() });
      setApiKey("");
      setEditing(false);
      load();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Could not save AI configuration.");
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    setBusy(true);
    try {
      await portalApi.removeAiConfig();
      load();
    } finally {
      setBusy(false);
    }
  }

  if (!status) return <Loader2 className="size-4 animate-spin text-faint" />;

  return (
    <Card>
      <div className="flex items-center gap-2">
        <Sparkles className="size-5 text-brand" />
        <h3 className="font-medium">AI</h3>
        <Badge tone={status.configured ? "good" : "muted"}>{status.configured ? "Configured" : "Not configured"}</Badge>
      </div>
      <p className="mt-1 text-sm text-muted">Used for AI Search and automated job matching. Your key is encrypted and never shared with other candidates.</p>

      {status.configured && !editing ? (
        <div className="mt-3 space-y-2">
          <p className="text-sm text-muted">
            Provider: <span className="text-foreground">Anthropic</span> · Model: <span className="text-foreground">{status.available_models.find((m) => m.id === status.model)?.label || status.model}</span>
          </p>
          <div className="flex gap-2">
            <Button variant="outline" onClick={() => setEditing(true)} disabled={busy}>
              Replace key
            </Button>
            <Button variant="ghost" onClick={remove} disabled={busy}>
              Remove
            </Button>
          </div>
        </div>
      ) : (
        <form onSubmit={save} className="mt-3 space-y-3">
          <div>
            <label className="text-xs text-faint">Provider</label>
            <p className="mt-1 text-sm text-muted">Anthropic</p>
          </div>
          <div>
            <label className="text-xs text-faint">Model</label>
            <select value={model} onChange={(e) => setModel(e.target.value)} className="mt-1 w-full max-w-sm rounded-md border border-border bg-surface px-3 py-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-brand/50">
              {status.available_models.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.label} — {m.cost_note}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="text-xs text-faint">API key</label>
            <input type="password" value={apiKey} onChange={(e) => setApiKey(e.target.value)} placeholder="sk-ant-..." className="mt-1 w-full max-w-sm rounded-md border border-border bg-surface px-3 py-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-brand/50" />
          </div>
          <div className="flex gap-2">
            <Button type="submit" disabled={busy || !apiKey.trim()}>
              Save
            </Button>
            {editing && (
              <Button type="button" variant="ghost" onClick={() => setEditing(false)} disabled={busy}>
                Cancel
              </Button>
            )}
          </div>
        </form>
      )}
      {message && <p className="mt-2 text-sm text-red-600 dark:text-red-400">{message}</p>}
    </Card>
  );
}
