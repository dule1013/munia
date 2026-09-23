"use client";

import { useState } from "react";
import Link from "next/link";
import { ChevronDown, Coins, Settings, Sparkles, X } from "lucide-react";
import { CompanyLogo } from "@/components/company-logo";
import { CostBadge } from "@/components/cost/cost-badge";
import { cn } from "@/lib/cn";

export type ShortItem = { url: string; company: string; role: string };

function fmtTokens(t: number): string {
  if (t >= 1_000_000) return `${(t / 1_000_000).toFixed(1)}M`;
  if (t >= 1_000) return `${Math.round(t / 1_000)}k`;
  return `${t}`;
}

// The persistent review-queue tray — bottom-sheet on mobile (thumb-zone), floating card
// on desktop. "Score shortlist" is the ONLY token spend in the whole inbox: cost is
// shown BEFORE the click and gated behind an explicit confirm (never spend by surprise).
export function ShortlistTray({
  items,
  estimate,
  hasCli,
  portalEnabled = false,
  configHref = "/config",
  onRemove,
  onClear,
  onScore,
}: {
  items: ShortItem[];
  estimate: { tokens?: number; usd?: number };
  hasCli: boolean;
  /** Manual per-job "Evaluate" scoring runs a local CLI subprocess with no
   * hosted equivalent yet — shows honest "not available" copy instead of
   * "not configured" (which would wrongly imply the candidate just needs to
   * set something up, when clicking through would still silently fail). */
  portalEnabled?: boolean;
  /** Where "Set up" sends the candidate — local mode's CLI lives under
   * /config, but hosted (portal) mode's AI configuration is the AIConfigPanel
   * on /discovery, not /config at all. */
  configHref?: string;
  onRemove: (url: string) => void;
  onClear: () => void;
  onScore: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [confirming, setConfirming] = useState(false);
  if (items.length === 0) return null;

  const n = items.length;
  const costText = estimate.tokens
    ? `≈ ${fmtTokens(estimate.tokens)} tokens${estimate.usd != null ? ` · ≈ $${estimate.usd.toFixed(2)}` : ""}`
    : "uses your tokens";

  return (
    <div className="fixed inset-x-0 bottom-0 z-30 sm:bottom-4">
      <div className="mx-auto w-full max-w-[120rem] sm:px-6">
        <div className="border-t border-border bg-surface shadow-lg shadow-black/10 sm:rounded-2xl sm:border">
          {/* expandable saved-items list */}
          {open && (
            <ul className="max-h-64 divide-y divide-border overflow-y-auto px-3 py-1">
              {items.map((it) => (
                <li key={it.url} className="flex items-center gap-2.5 py-2">
                  <CompanyLogo name={it.company} size={18} />
                  <span className="min-w-0 flex-1 truncate text-sm">
                    <span className="font-medium">{it.company}</span> <span className="text-muted-foreground">· {it.role}</span>
                  </span>
                  <button
                    type="button"
                    onClick={() => onRemove(it.url)}
                    aria-label={`Remove ${it.company}`}
                    className="inline-flex items-center justify-center rounded-md p-1 text-faint transition-colors hover:text-foreground max-sm:min-h-[44px] max-sm:min-w-[44px]"
                  >
                    <X className="size-4" />
                  </button>
                </li>
              ))}
            </ul>
          )}

          {/* the persistent bar */}
          <div className="flex items-center gap-3 px-3 py-2.5 sm:px-4">
            <button
              type="button"
              onClick={() => setOpen((v) => !v)}
              className="inline-flex items-center gap-1.5 text-sm font-medium max-sm:min-h-[44px]"
            >
              <ChevronDown className={cn("size-4 text-muted-foreground transition-transform", open && "rotate-180")} />
              Review queue <span className="tabular-nums text-brand-text">({n})</span>
            </button>

            {open && (
              <button type="button" onClick={onClear} className="text-xs text-faint transition-colors hover:text-foreground max-sm:min-h-[44px]">
                Clear
              </button>
            )}

            <div className="ml-auto flex items-center gap-2">
              {!confirming ? (
                <button
                  type="button"
                  onClick={() => setConfirming(true)}
                  className="inline-flex items-center gap-2 rounded-full bg-brand px-4 py-2 text-sm font-medium text-brand-foreground transition-colors hover:bg-brand-200 max-sm:min-h-[44px]"
                >
                  <Sparkles className="size-4" />
                  <span>Evaluate {n}</span>
                  <span className="hidden text-xs font-normal text-brand-foreground/80 sm:inline">· {costText}</span>
                </button>
              ) : (
                <ConfirmScore n={n} costText={costText} hasCli={hasCli} portalEnabled={portalEnabled} configHref={configHref} onCancel={() => setConfirming(false)} onConfirm={() => { setConfirming(false); onScore(); }} />
              )}
            </div>
          </div>

          {/* cost line — always visible on mobile (where it doesn't fit in the button) */}
          <div className="flex items-center gap-2 border-t border-border/60 px-3 py-1.5 text-[11px] text-muted-foreground sm:hidden">
            <CostBadge kind="spend" size="xs" />
            <span>{costText} — the only step that spends</span>
          </div>
        </div>
      </div>
    </div>
  );
}

function ConfirmScore({
  n,
  costText,
  hasCli,
  portalEnabled,
  configHref,
  onCancel,
  onConfirm,
}: {
  n: number;
  costText: string;
  hasCli: boolean;
  portalEnabled: boolean;
  configHref: string;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  if (!hasCli && portalEnabled) {
    return (
      <div className="flex items-center gap-2 text-xs">
        <span className="text-muted-foreground">Manual scoring isn&apos;t available in hosted mode yet — Munia scores automatically every morning.</span>
        <button type="button" onClick={onCancel} className="text-faint hover:text-foreground max-sm:min-h-[44px]">
          Dismiss
        </button>
      </div>
    );
  }
  if (!hasCli) {
    return (
      <div className="flex items-center gap-2 text-xs">
        <span className="text-muted-foreground">No AI configured.</span>
        <Link href={configHref} className="inline-flex items-center gap-1 rounded-full border border-brand/40 bg-brand-soft px-3 py-1.5 font-medium text-brand max-sm:min-h-[44px]">
          <Settings className="size-3.5" /> Set up
        </Link>
        <button type="button" onClick={onCancel} className="text-faint hover:text-foreground max-sm:min-h-[44px]">
          Cancel
        </button>
      </div>
    );
  }
  return (
    <div className="flex items-center gap-2">
      <span className="hidden items-center gap-1 text-[11px] text-muted-foreground sm:inline-flex">
        <Coins className="size-3.5 text-brand" /> {costText}
      </span>
      <button
        type="button"
        onClick={onConfirm}
        className="inline-flex items-center gap-1.5 rounded-full bg-brand px-4 py-2 text-sm font-medium text-brand-foreground transition-colors hover:bg-brand-200 max-sm:min-h-[44px]"
      >
        Evaluate {n} now
      </button>
      <button type="button" onClick={onCancel} className="rounded-full px-2 py-2 text-xs text-faint transition-colors hover:text-foreground max-sm:min-h-[44px]">
        Cancel
      </button>
    </div>
  );
}
