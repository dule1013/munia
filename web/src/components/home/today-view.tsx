"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { ArrowRight, Loader2, Sparkles } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { CompanyLogo } from "@/components/company-logo";
import { JobProvenance } from "@/components/discovery/job-provenance";
import { portalApi, type CandidateJob, type TodaySummary } from "@/lib/api-client";

function daysAgo(iso: string | null): string | null {
  if (!iso) return null;
  const days = Math.floor((Date.now() - new Date(iso).getTime()) / 86_400_000);
  if (days <= 0) return "today";
  if (days === 1) return "1 day ago";
  return `${days} days ago`;
}

/** Munia's main daily landing page (Phase 5 follow-up §10) — ONLY the
 * strongest, still-actionable opportunities (GET /pipeline/today), newest
 * qualification first, cumulative across days. Everything else (uncertain
 * jobs, scanner activity, raw counts) lives in Pipeline → Inbox instead. */
export function TodayView() {
  const [items, setItems] = useState<CandidateJob[] | null>(null);
  const [summary, setSummary] = useState<TodaySummary | null>(null);

  useEffect(() => {
    portalApi.today().then(setItems).catch(() => setItems([]));
    portalApi.todaySummary().then(setSummary).catch(() => setSummary(null));
  }, []);

  if (items === null) {
    return (
      <div className="mx-auto w-full max-w-[120rem] px-6 py-16 text-center">
        <Loader2 className="mx-auto size-6 animate-spin text-faint" />
      </div>
    );
  }

  return (
    <div className="mx-auto w-full max-w-[120rem] px-6 py-8">
      <div className="flex items-center gap-3">
        <Sparkles className="size-6 text-brand" />
        <h1 className="font-sans text-3xl font-semibold tracking-tight text-landing">Today</h1>
      </div>
      {summary && (
        <p className="mt-2 max-w-2xl text-sm text-muted-foreground">
          {summary.new > 0 && (
            <>
              <span className="font-semibold text-foreground">{summary.new}</span> new strong match{summary.new === 1 ? "" : "es"} ·{" "}
            </>
          )}
          <span className="font-semibold text-foreground">{summary.current}</span> strong opportunit{summary.current === 1 ? "y" : "ies"} awaiting review
        </p>
      )}

      {items.length === 0 ? (
        <Card className="mt-6 max-w-2xl">
          <p className="text-sm text-muted-foreground">No strong matches yet. Munia keeps searching every morning — check{" "}
            <Link href="/pipeline" className="font-medium underline underline-offset-2">Pipeline → Inbox</Link> for everything plausibly worth a look in the meantime.
          </p>
        </Card>
      ) : (
        <ul className="mt-6 grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
          {items.map((item) => (
            <li key={item.id}>
              <Link href={`/pipeline/${item.id}`} className="block h-full">
                <Card className="flex h-full flex-col transition-colors hover:bg-surface-hover">
                  <div className="flex items-start gap-3">
                    <CompanyLogo name={item.job.company} size={36} />
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <h3 className="font-medium">{item.job.title}</h3>
                        <Badge tone="good">Strong match</Badge>
                      </div>
                      <p className="text-sm text-muted-foreground">
                        {item.job.company}
                        {item.job.location ? ` · ${item.job.location}` : ""}
                        {daysAgo(item.job.posted_at) ? ` · ${daysAgo(item.job.posted_at)}` : ""}
                      </p>
                    </div>
                    <ArrowRight className="mt-1 size-4 shrink-0 text-faint" />
                  </div>
                  {item.ai_fit_reason && <p className="mt-2 line-clamp-3 text-sm text-foreground">{item.ai_fit_reason}</p>}
                  <div className="mt-auto pt-2">
                    <JobProvenance jobId={item.job_id} />
                  </div>
                </Card>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
