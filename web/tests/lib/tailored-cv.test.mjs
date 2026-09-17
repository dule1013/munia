import assert from "node:assert/strict";
import { test } from "node:test";
import { manualEditMarkerPath, parsePdfIndexEntries, pdfIndexEntryForReport } from "../../src/lib/tailored-cv.mjs";

test("parsePdfIndexEntries retains the report to HTML and PDF relationship", () => {
  const index = [
    "# report\tpdf\thtml\tformat\tdate",
    "002\toutput/cv-super.pdf\toutput/cv-super.html\ta4\t2026-09-15",
  ].join("\n");
  assert.deepEqual(parsePdfIndexEntries(index), [{
    report: 2,
    pdf: "output/cv-super.pdf",
    html: "output/cv-super.html",
    format: "a4",
    date: "2026-09-15",
  }]);
});

test("pdfIndexEntryForReport matches normalized report numbers", () => {
  const index = "003\toutput/cv-gartner.pdf\toutput/cv-gartner.html\tletter\t2026-09-15\n";
  assert.equal(pdfIndexEntryForReport(index, "3")?.html, "output/cv-gartner.html");
  assert.equal(pdfIndexEntryForReport(index, "4"), null);
});

test("manual edit marker stays adjacent to one tailored HTML file", () => {
  assert.equal(manualEditMarkerPath("/root/output/cv-super.html"), "/root/output/cv-super.html.manual-edit.json");
  assert.notEqual(manualEditMarkerPath("/root/output/cv-super.html"), manualEditMarkerPath("/root/output/cv-gartner.html"));
});
