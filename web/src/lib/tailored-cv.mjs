export function parsePdfIndexEntries(indexText) {
  const entries = [];
  for (const line of String(indexText ?? "").split(/\r?\n/)) {
    if (!line.trim() || line.startsWith("#")) continue;
    const [rawReport, rawPdf, rawHtml, rawFormat, rawDate] = line.split("\t");
    const reportText = rawReport?.trim() ?? "";
    if (!/^\d+$/.test(reportText)) continue;
    entries.push({
      report: Number(reportText),
      pdf: rawPdf?.trim() || null,
      html: rawHtml?.trim() || null,
      format: rawFormat?.trim() === "letter" ? "letter" : "a4",
      date: rawDate?.trim() || null,
    });
  }
  return entries;
}

export function pdfIndexEntryForReport(indexText, report) {
  const value = String(report ?? "").trim();
  if (!/^\d+$/.test(value)) return null;
  return parsePdfIndexEntries(indexText).find((entry) => entry.report === Number(value)) ?? null;
}

export function manualEditMarkerPath(htmlPath) {
  return `${htmlPath}.manual-edit.json`;
}
