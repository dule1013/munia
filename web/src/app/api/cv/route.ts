import { NextRequest, NextResponse } from "next/server";
import { execFile, spawn } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { careerOpsRoot, rootScript, tailoredCvForReport } from "@/lib/career-ops";
import { atomicWrite, atomicWriteWithBackup } from "@/lib/core/safe-write";
import { renderAndMarkPdf } from "@/lib/pdf-render.mjs";
import { saveTailoredCv } from "@/lib/tailored-cv-save.mjs";

function cvPath() {
  return path.join(careerOpsRoot(), "cv.md");
}

const MAX_MASTER_CV_BYTES = 200_000;
const MAX_TAILORED_CV_BYTES = 500_000;

function validateCandidate(file: string): Promise<{ ok: boolean; output: string }> {
  return new Promise((resolve) => {
    execFile(process.execPath, [rootScript("verify-cv-facts"), file], { cwd: careerOpsRoot() }, (error, stdout, stderr) => {
      resolve({ ok: !error, output: `${stdout || ""}${stderr || ""}`.trim() });
    });
  });
}

export async function GET(req: NextRequest) {
  const report = (req.nextUrl.searchParams.get("report") ?? "").trim();
  if (report) {
    const tailored = await tailoredCvForReport(report);
    if (!tailored) return NextResponse.json({ error: "editable tailored CV not found" }, { status: 404 });
    return NextResponse.json({
      content: tailored.content,
      exists: true,
      reportId: tailored.reportId,
      applicationId: tailored.applicationId,
      company: tailored.company,
      role: tailored.role,
      manuallyEdited: tailored.manuallyEdited,
      pdfReady: tailored.pdfReady,
    });
  }
  try {
    return NextResponse.json({ content: fs.readFileSync(cvPath(), "utf8"), exists: true });
  } catch {
    return NextResponse.json({ content: "", exists: false });
  }
}

export async function POST(req: NextRequest) {
  let body: { content?: string; report?: string };
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: "bad json" }, { status: 400 });
  }
  if (typeof body.content !== "string") {
    return NextResponse.json({ error: "content required" }, { status: 400 });
  }
  const report = typeof body.report === "string" ? body.report.trim() : "";
  const maxBytes = report ? MAX_TAILORED_CV_BYTES : MAX_MASTER_CV_BYTES;
  if (Buffer.byteLength(body.content, "utf8") > maxBytes) {
    return NextResponse.json({ error: `CV is too large (over ${maxBytes / 1000}KB)` }, { status: 413 });
  }

  if (!report) {
    // DATA_CONTRACT: cv.md is user-layer and gitignored (no git recovery). Never
    // blind-overwrite — snapshot the prior CV to a .bak first, write atomically.
    try {
      const bak = atomicWriteWithBackup(cvPath(), body.content);
      return NextResponse.json({ ok: true, backedUp: !!bak });
    } catch {
      return NextResponse.json({ error: "write failed" }, { status: 500 });
    }
  }
  if (!/^\d+$/.test(report)) return NextResponse.json({ error: "invalid report number" }, { status: 400 });

  const tailored = await tailoredCvForReport(report);
  if (!tailored?.htmlPath || !tailored.pdfPath) {
    return NextResponse.json({ error: "This tailored CV has no editable HTML source. Regenerate it from the job first." }, { status: 409 });
  }

  try {
    const result = await saveTailoredCv({
      content: body.content,
      reportId: tailored.reportId,
      htmlPath: tailored.htmlPath,
      pdfPath: tailored.pdfPath,
      format: tailored.format,
      root: careerOpsRoot(),
      validate: validateCandidate,
      atomicWrite,
      atomicWriteWithBackup,
      render: ({ html, finalPdf, format, reportId }: { html: string; finalPdf: string; format: "a4" | "letter"; reportId: string }) => renderAndMarkPdf({
        spawnFn: spawn,
        execPath: process.execPath,
        root: careerOpsRoot(),
        pdfPaths: { html, finalPdf },
        format,
        reportNum: reportId,
      }),
    });
    const { status, ...payload } = result;
    return NextResponse.json(payload, { status });
  } catch {
    return NextResponse.json({ error: "write failed" }, { status: 500 });
  }
}
