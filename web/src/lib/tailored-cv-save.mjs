import fs from "node:fs";
import path from "node:path";
import { randomUUID } from "node:crypto";
import { manualEditMarkerPath } from "./tailored-cv.mjs";

export function manualOverwriteRequired(manuallyEdited, confirmed) {
  return manuallyEdited === true && confirmed !== true;
}

export async function saveTailoredCv({
  content,
  reportId,
  htmlPath,
  pdfPath,
  format,
  root,
  validate,
  render,
  atomicWrite,
  atomicWriteWithBackup,
}) {
  const tempDir = path.join(root, ".career-ops-web", "cv-edit");
  fs.mkdirSync(tempDir, { recursive: true });
  const temp = path.join(tempDir, `report-${reportId}-${randomUUID()}.html`);
  try {
    fs.writeFileSync(temp, content, "utf8");
    const validation = await validate(temp);
    if (!validation.ok) return { ok: false, status: 422, error: "Fact validation failed", details: validation.output };

    const backup = atomicWriteWithBackup(htmlPath, content);
    atomicWrite(manualEditMarkerPath(htmlPath), JSON.stringify({ report: reportId, editedAt: new Date().toISOString() }) + "\n");
    const result = await render({ html: htmlPath, finalPdf: pdfPath, format, reportId });
    if (result.kind === "render-failed") {
      return { ok: false, status: 500, error: result.error, saved: true, backedUp: Boolean(backup) };
    }
    return { ok: true, status: 200, backedUp: Boolean(backup), pdfRefreshed: true, manuallyEdited: true, warnings: result.warnings };
  } finally {
    try { fs.rmSync(temp, { force: true }); } catch {}
  }
}
