import { execFile } from "node:child_process";
import { NextResponse } from "next/server";
import { careerOpsRoot, rootScript } from "@/lib/career-ops";
import { canonicalizeStatus } from "@/lib/core/states";
import { clientErrorMessage, parseCliJson, trackerRowArg } from "@/lib/status-cli.mjs";
import { serverApi } from "@/lib/api-server";
import { portalMode } from "@/lib/portal-mode.mjs";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

function localStatus(row: string, status: string) {
  return new Promise<{ code: number; stdout: string; stderr: string }>((resolve) => {
    execFile(process.execPath, [rootScript("set-status"), "--row", row, status, "--source", "web", "--json"], { cwd: careerOpsRoot(), timeout: 30_000 }, (error, stdout, stderr) => resolve({ code: typeof error?.code === "number" ? error.code : error ? 1 : 0, stdout: stdout || "", stderr: stderr || "" }));
  });
}

export async function POST(req: Request) {
  const body = await req.json().catch(() => null) as { n?: unknown; status?: unknown } | null;
  const status = typeof body?.status === "string" ? canonicalizeStatus(body.status) : null;
  if (!status) return NextResponse.json({ error: "canonical status required" }, { status: 400 });
  if (portalMode()) {
    if (typeof body?.n !== "string" || !body.n) return NextResponse.json({ error: "candidate job id required" }, { status: 400 });
    const item = await serverApi(`/pipeline/${encodeURIComponent(body.n)}`, { method: "PATCH", body: JSON.stringify({ pipeline_status: status }) });
    return NextResponse.json({ ok: true, status, item });
  }
  const row = trackerRowArg(body?.n);
  if (!row) return NextResponse.json({ error: "tracker row required" }, { status: 400 });
  const result = await localStatus(row, status);
  const parsed = parseCliJson(result.stdout);
  if (result.code !== 0) return NextResponse.json({ error: clientErrorMessage(parsed, result.stderr) }, { status: 500 });
  if (!parsed) return NextResponse.json({ error: "status update returned no result" }, { status: 500 });
  return NextResponse.json({ ok: true, status, changed: parsed.changed === true, statusLogged: parsed.statusLogged === true });
}
