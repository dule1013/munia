import Link from "next/link";
import { ExternalLink, FilePenLine, FileText, ShieldCheck } from "lucide-react";
import type { TailoredCv } from "@/lib/career-ops";
import { Badge } from "@/components/ui/badge";
import { portalMode } from "@/lib/portal-mode.mjs";

function dateLabel(value: string) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return value || "Unknown";
  return new Date(`${value}T00:00:00Z`).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
}

export function CvLibrary({ master, tailored }: { master: { name: string; modifiedDate: string; exists: boolean }; tailored: TailoredCv[] }) {
  return (
    <div className="mx-auto w-full max-w-[120rem] px-4 py-8 sm:px-6 lg:px-8">
      <header>
        <h1 className="font-display text-3xl tracking-tight text-landing">CV workspace</h1>
        <p className="mt-1 text-sm text-muted-foreground">Keep your factual master separate from job-specific application documents.</p>
      </header>

      <section className="mt-8">
        <h2 className="text-xs font-semibold uppercase tracking-[0.16em] text-muted-foreground">Master CV</h2>
        <div className="mt-3 flex flex-col gap-4 rounded-2xl border border-border bg-surface/50 p-5 sm:flex-row sm:items-center">
          <div className="grid size-11 shrink-0 place-items-center rounded-xl bg-brand-soft text-brand">
            <ShieldCheck className="size-5" />
          </div>
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <h3 className="font-display text-xl text-landing">{master.name}</h3>
              <Badge tone="good">Source of truth</Badge>
            </div>
            <p className="mt-1 text-sm text-muted-foreground">Canonical factual career history used by every evaluation and tailored CV.</p>
            {master.modifiedDate && <p className="mt-1 text-xs text-faint">Last updated {dateLabel(master.modifiedDate)}</p>}
          </div>
          <Link href="/cv/master" className="inline-flex items-center justify-center gap-1.5 rounded-full bg-brand px-4 py-2 text-sm font-medium text-brand-foreground hover:bg-brand-200">
            <FilePenLine className="size-4" /> Edit
          </Link>
        </div>
      </section>

      <section className="mt-10">
        <div>
          <h2 className="text-xs font-semibold uppercase tracking-[0.16em] text-muted-foreground">Tailored CVs</h2>
          <p className="mt-1 text-sm text-muted-foreground">Application-specific HTML sources and their rendered PDFs.</p>
        </div>
        {tailored.length === 0 ? (
          <div className="mt-3 rounded-2xl border border-dashed border-border bg-surface/30 px-6 py-10 text-center text-sm text-muted-foreground">
            No tailored CVs yet. They will appear here when you generate a CV for a job.
          </div>
        ) : (
          <div className="mt-3 grid gap-3">
            {tailored.map((cv) => (
              <article key={cv.reportId} className="rounded-2xl border border-border bg-surface/40 p-5">
                <div className="flex flex-col gap-4 lg:flex-row lg:items-center">
                  <div className="grid size-10 shrink-0 place-items-center rounded-xl bg-surface-hover text-muted-foreground">
                    <FileText className="size-5" />
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <h3 className="font-display text-xl text-landing">{cv.company}</h3>
                      {cv.manuallyEdited && <Badge tone="warn">Manually edited</Badge>}
                      {!cv.editable && <Badge tone="muted">PDF only</Badge>}
                    </div>
                    <p className="mt-0.5 text-sm text-foreground">{cv.role}</p>
                    <p className="mt-1 text-xs text-faint">
                      Updated {dateLabel(cv.modifiedDate)} · {cv.score || "Unscored"} · {cv.status}
                    </p>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {cv.editable ? (
                      <Link href={`/cv/${cv.reportId}`} className="inline-flex items-center justify-center gap-1.5 rounded-full bg-brand px-3.5 py-2 text-xs font-medium text-brand-foreground hover:bg-brand-200">
                        <FilePenLine className="size-3.5" /> Edit
                      </Link>
                    ) : (
                      <Link href={`/pipeline/${cv.applicationId}`} className="inline-flex items-center justify-center rounded-full border border-border px-3.5 py-2 text-xs font-medium text-muted-foreground hover:border-brand/40 hover:text-brand">
                        Regenerate to edit
                      </Link>
                    )}
                    {cv.pdfReady && (
                      <a href={portalMode() ? `/api/backend/cvs/${encodeURIComponent(cv.reportId)}/pdf` : `/api/cv-pdf?n=${encodeURIComponent(cv.reportId)}&company=${encodeURIComponent(cv.company)}`} target="_blank" rel="noreferrer" className="inline-flex items-center justify-center gap-1.5 rounded-full border border-border px-3.5 py-2 text-xs font-medium text-muted-foreground hover:border-brand/40 hover:text-brand">
                        View PDF <ExternalLink className="size-3.5" />
                      </a>
                    )}
                    <Link href={`/pipeline/${cv.applicationId}`} className="inline-flex items-center justify-center rounded-full border border-border px-3.5 py-2 text-xs font-medium text-muted-foreground hover:border-brand/40 hover:text-brand">
                      View Job
                    </Link>
                  </div>
                </div>
              </article>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
