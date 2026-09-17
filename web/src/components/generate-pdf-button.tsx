"use client";

import { useMemo } from "react";
import Link from "next/link";
import { FileDown, FilePenLine, Loader2, FileText, RotateCcw } from "lucide-react";
import { useJobs } from "@/components/jobs/job-store";
import { CostBadge } from "@/components/cost/cost-badge";
import { usePortalMode } from "@/components/portal-mode-provider";

// Fires the real career-ops `pdf` mode (worker kind "pdf") to generate an
// ATS-optimized CV tailored to THIS offer → output/cv-… + marks the tracker.
// Once a tailored CV exists (tracker PDF ✅, or a pdf worker just finished), it
// becomes a "View tailored CV" link (served by /api/cv-pdf) + a regenerate icon.
export function GeneratePdfButton({ n, company, pdfReady, editable = false, manuallyEdited = false }: { n: string; company: string; pdfReady: boolean; editable?: boolean; manuallyEdited?: boolean }) {
  const { jobs, startJob } = useJobs();
  const portalEnabled = usePortalMode();
  const job = useMemo(
    () => jobs.filter((j) => j.kind === "pdf" && j.input === n).sort((a, b) => b.startedAt - a.startedAt)[0],
    [jobs, n],
  );
  const generate = () => {
    if (manuallyEdited && !window.confirm("This tailored CV has manual edits. Replace them with a new AI-generated version?")) return;
    startJob({
      title: `CV PDF · ${company}`,
      subtitle: "tailored for this role",
      kind: "pdf",
      input: n,
      page: `/pipeline/${n}`,
      confirmManualOverwrite: manuallyEdited,
    });
  };

  if (job?.status === "running")
    return (
      <Link href={`/jobs/${job.id}`} className="inline-flex items-center justify-center gap-1.5 rounded-full border border-brand/40 bg-brand-soft px-3 py-1 text-xs font-medium text-brand max-sm:min-h-[44px]">
        <Loader2 className="size-3.5 animate-spin" /> Generating CV…
      </Link>
    );

  const ready = pdfReady || job?.status === "done";
  if (ready)
    return (
      <span className="inline-flex items-center gap-1">
        {editable && (
          <Link
            href={`/cv/${encodeURIComponent(n)}`}
            className="inline-flex items-center justify-center gap-1.5 rounded-full border border-brand/35 bg-brand-soft px-3 py-1 text-xs font-medium text-brand max-sm:min-h-[44px]"
          >
            <FilePenLine className="size-3.5" /> Edit CV
          </Link>
        )}
        <a
          href={portalEnabled ? `/api/backend/cvs/${encodeURIComponent(n)}/pdf` : `/api/cv-pdf?n=${encodeURIComponent(n)}&company=${encodeURIComponent(company)}`}
          target="_blank"
          rel="noreferrer"
          className="inline-flex items-center justify-center gap-1.5 rounded-full border border-emerald-500/40 bg-emerald-500/10 px-3 py-1 text-xs font-medium text-emerald-700 transition-colors hover:bg-emerald-500/15 dark:text-emerald-400 max-sm:min-h-[44px]"
        >
          <FileText className="size-3.5" /> View tailored CV
        </a>
        <button
          onClick={generate}
          title="Regenerate the tailored CV"
          className="inline-flex items-center justify-center rounded-full p-1 text-faint transition-colors hover:text-brand max-sm:min-h-[44px] max-sm:min-w-[44px]"
        >
          <RotateCcw className="size-3" />
        </button>
      </span>
    );

  // Point-of-action cost affordance: generating a tailored CV runs the user's
  // AI (spends tokens). Surface it right on the trigger so cost is never a
  // surprise — the community's #1 pain (mirrors Explore's token-honesty).
  return (
    <span className="inline-flex items-center gap-1.5">
      <button
        onClick={generate}
        className="inline-flex items-center justify-center gap-1.5 rounded-full border border-border px-3 py-1 text-xs font-medium text-muted transition-colors hover:border-brand/40 hover:text-brand max-sm:min-h-[44px]"
        title="Generate an ATS-optimized CV tailored to this role"
      >
        <FileDown className="size-3.5" /> Generate tailored CV (PDF)
      </button>
      <CostBadge kind="spend" size="xs" />
    </span>
  );
}
