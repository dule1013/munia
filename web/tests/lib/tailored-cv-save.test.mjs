import assert from "node:assert/strict";
import { test } from "node:test";
import { mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync, existsSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { manualOverwriteRequired, saveTailoredCv } from "../../src/lib/tailored-cv-save.mjs";
import { manualEditMarkerPath } from "../../src/lib/tailored-cv.mjs";

function write(file, content) {
  mkdirSync(join(file, ".."), { recursive: true });
  writeFileSync(file, content, "utf8");
}

function writeWithBackup(file, content) {
  const backup = `${file}.bak`;
  if (existsSync(file)) writeFileSync(backup, readFileSync(file));
  write(file, content);
  return backup;
}

test("manualOverwriteRequired blocks silent AI replacement", () => {
  assert.equal(manualOverwriteRequired(true, false), true);
  assert.equal(manualOverwriteRequired(true, true), false);
  assert.equal(manualOverwriteRequired(false, false), false);
});

test("saving one tailored CV validates, preserves other CVs and master, and refreshes its PDF", async () => {
  const root = mkdtempSync(join(tmpdir(), "co-tailored-save-"));
  const master = join(root, "cv.md");
  const superHtml = join(root, "output", "cv-super.html");
  const superPdf = join(root, "output", "cv-super.pdf");
  const gartnerHtml = join(root, "output", "cv-gartner.html");
  write(master, "master unchanged");
  write(superHtml, "old super");
  write(gartnerHtml, "other tailored unchanged");
  try {
    const result = await saveTailoredCv({
      content: "manual Super wording",
      reportId: "2",
      htmlPath: superHtml,
      pdfPath: superPdf,
      format: "a4",
      root,
      validate: async (file) => ({ ok: readFileSync(file, "utf8").includes("manual"), output: "" }),
      atomicWrite: write,
      atomicWriteWithBackup: writeWithBackup,
      render: async ({ html, finalPdf }) => {
        write(finalPdf, `PDF:${readFileSync(html, "utf8")}`);
        return { kind: "rendered", warnings: [] };
      },
    });
    assert.equal(result.ok, true);
    assert.equal(readFileSync(superHtml, "utf8"), "manual Super wording");
    assert.equal(readFileSync(superPdf, "utf8"), "PDF:manual Super wording");
    assert.equal(readFileSync(master, "utf8"), "master unchanged");
    assert.equal(readFileSync(gartnerHtml, "utf8"), "other tailored unchanged");
    assert.equal(existsSync(manualEditMarkerPath(superHtml)), true);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test("failed fact validation leaves every persisted CV untouched", async () => {
  const root = mkdtempSync(join(tmpdir(), "co-tailored-invalid-"));
  const html = join(root, "output", "cv-super.html");
  write(html, "verified original");
  try {
    const result = await saveTailoredCv({
      content: "invented claim",
      reportId: "2",
      htmlPath: html,
      pdfPath: join(root, "output", "cv-super.pdf"),
      format: "a4",
      root,
      validate: async () => ({ ok: false, output: "unsupported metric" }),
      atomicWrite: write,
      atomicWriteWithBackup: writeWithBackup,
      render: async () => { throw new Error("must not render"); },
    });
    assert.equal(result.status, 422);
    assert.equal(readFileSync(html, "utf8"), "verified original");
    assert.equal(existsSync(manualEditMarkerPath(html)), false);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});
