"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { ArrowLeft, Check, ExternalLink, Loader2 } from "lucide-react";
import { cn } from "@/lib/cn";
import { Badge } from "@/components/ui/badge";
import { usePortalMode } from "@/components/portal-mode-provider";

type Props =
  | { mode: "master" }
  | { mode: "tailored"; reportId: string; applicationId: string; company: string; role: string; pdfReady: boolean };

export function CvEditor(props: Props) {
  const tailored = props.mode === "tailored";
  const portalEnabled = usePortalMode();
  const endpoint = portalEnabled
    ? tailored ? `/api/backend/cvs/${encodeURIComponent(props.reportId)}` : "/api/backend/candidate/profile"
    : tailored ? `/api/cv?report=${encodeURIComponent(props.reportId)}` : "/api/cv";
  const [content, setContent] = useState("");
  const [loaded, setLoaded] = useState(false);
  const [exists, setExists] = useState(true);
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [manuallyEdited, setManuallyEdited] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    setLoaded(false);
    fetch(endpoint)
      .then(async (r) => ({ ok: r.ok, data: await r.json() }))
      .then(({ ok, data }) => {
        if (!ok) throw new Error(data.error || "Could not load CV");
        const value = portalEnabled ? (tailored ? data.source_html : data.master_cv) : data.content;
        setContent(value ?? "");
        setExists(portalEnabled ? Boolean(value) : data.exists ?? false);
        setManuallyEdited(portalEnabled ? data.manually_edited === true : data.manuallyEdited === true);
      })
      .catch((e) => setError(e instanceof Error ? e.message : "Could not load CV"))
      .finally(() => setLoaded(true));
  }, [endpoint]);

  async function save() {
    setSaving(true);
    setError("");
    try {
      const saveEndpoint = portalEnabled ? (tailored ? `/api/backend/cvs/${encodeURIComponent(props.reportId)}` : "/api/backend/candidate/master-cv") : "/api/cv";
      const res = await fetch(saveEndpoint, {
        method: portalEnabled ? "PUT" : "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(portalEnabled ? (tailored ? { source_html: content } : { content }) : { content, ...(tailored ? { report: props.reportId } : {}) }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        setError(data.details || data.error || "Save failed");
        return;
      }
      setDirty(false);
      setExists(true);
      setManuallyEdited(tailored || (portalEnabled ? data.manually_edited === true : data.manuallyEdited === true));
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } finally {
      setSaving(false);
    }
  }

  const title = tailored ? props.company : "Master CV";
  const subtitle = tailored ? props.role : "Edit the canonical factual source used by every evaluation and tailored CV.";
  const previewTitle = useMemo(() => tailored ? `${props.company} tailored CV preview` : "Master CV preview", [props, tailored]);
  const pdfHref = tailored ? (portalEnabled ? `/api/backend/cvs/${encodeURIComponent(props.reportId)}/pdf` : `/api/cv-pdf?n=${encodeURIComponent(props.reportId)}&company=${encodeURIComponent(props.company)}`) : "";

  return (
    <div className="mx-auto w-full max-w-[120rem] px-4 py-8 sm:px-6 lg:px-8">
      <Link href="/cv" className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-brand">
        <ArrowLeft className="size-4" /> CV workspace
      </Link>
      <div className="mt-5 flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="font-display text-3xl tracking-tight text-landing">{title}</h1>
            {tailored ? <Badge tone="muted">Tailored CV</Badge> : <Badge tone="good">Source of truth</Badge>}
            {manuallyEdited && <Badge tone="warn">Manually edited</Badge>}
          </div>
          <p className="mt-1 text-sm text-muted-foreground">{subtitle}</p>
          {!tailored && !exists && loaded && <p className="mt-1 text-xs text-faint">No cv.md yet — start typing to create it.</p>}
          {tailored && (
            <Link href={`/pipeline/${props.applicationId}`} className="mt-2 inline-flex items-center gap-1 text-xs font-medium text-brand hover:underline">
              View job and evaluation <ExternalLink className="size-3" />
            </Link>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {tailored && props.pdfReady && (
            <a href={pdfHref} target="_blank" rel="noreferrer" className="inline-flex items-center justify-center gap-1.5 rounded-full border border-border px-4 py-2 text-sm font-medium text-muted-foreground hover:border-brand/40 hover:text-brand">
              View PDF <ExternalLink className="size-3.5" />
            </a>
          )}
          <button
            type="button"
            onClick={save}
            disabled={saving || !dirty}
            className={cn(
              "inline-flex items-center justify-center gap-2 rounded-full px-5 py-2 text-sm font-medium transition-colors max-sm:min-h-[44px]",
              dirty ? "bg-brand text-brand-foreground hover:bg-brand-200" : "border border-border bg-surface text-muted-foreground",
            )}
          >
            {saving ? <Loader2 className="size-4 animate-spin" /> : saved ? <Check className="size-4" /> : null}
            {saved ? "Saved" : tailored ? "Save and refresh PDF" : "Save"}
          </button>
        </div>
      </div>

      {error && <div className="mt-4 whitespace-pre-wrap rounded-xl border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-700 dark:text-red-300">{error}</div>}

      {!loaded ? (
        <div className="mt-6 text-sm text-muted-foreground">Loading…</div>
      ) : (
        <div className="mt-6 grid min-w-0 gap-4 xl:grid-cols-2">
          <textarea
            value={content}
            onChange={(e) => { setContent(e.target.value); setDirty(true); }}
            spellCheck={false}
            placeholder={tailored ? "<!doctype html>…" : "# Your Name\n\n## Summary\n…"}
            className="min-h-[72vh] min-w-0 w-full resize-y rounded-2xl border border-border bg-surface/50 p-4 font-mono text-sm leading-relaxed outline-none transition-colors placeholder:text-faint focus:border-brand/40"
          />
          {tailored ? (
            <div className="min-h-[72vh] min-w-0 overflow-hidden rounded-2xl border border-border bg-white">
              <iframe title={previewTitle} srcDoc={content} sandbox="" className="h-[72vh] w-full bg-white" />
            </div>
          ) : (
            <article className="report-prose min-h-[72vh] min-w-0 overflow-auto rounded-2xl border border-border bg-surface/30 p-5">
              {content.trim() ? <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown> : <p className="text-muted-foreground">Preview appears here.</p>}
            </article>
          )}
        </div>
      )}
    </div>
  );
}
