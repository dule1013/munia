import { auth } from "@clerk/nextjs/server";
import type { NextRequest } from "next/server";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export const maxDuration = 800;

const API_URL = process.env.CAREER_OPS_API_URL || "http://127.0.0.1:8000";

async function forward(req: NextRequest, segments: string[]) {
  const session = await auth();
  if (!session.userId) return Response.json({ detail: "unauthorized" }, { status: 401 });
  const token = await session.getToken();
  if (!token) return Response.json({ detail: "unauthorized" }, { status: 401 });
  const upstream = new URL(`/api/v1/${segments.map(encodeURIComponent).join("/")}`, API_URL);
  upstream.search = req.nextUrl.search;
  const headers = new Headers({ Authorization: `Bearer ${token}`, Accept: req.headers.get("accept") || "application/json" });
  const contentType = req.headers.get("content-type");
  if (contentType) headers.set("Content-Type", contentType);
  const response = await fetch(upstream, { method: req.method, headers, body: req.method === "GET" || req.method === "HEAD" ? undefined : await req.arrayBuffer(), cache: "no-store" });
  const responseHeaders = new Headers();
  for (const header of ["content-type", "content-disposition", "cache-control"]) {
    const value = response.headers.get(header);
    if (value) responseHeaders.set(header, value);
  }
  return new Response(response.body, { status: response.status, headers: responseHeaders });
}

type Context = { params: Promise<{ path: string[] }> };
const handler = async (req: NextRequest, context: Context) => forward(req, (await context.params).path);

export { handler as GET, handler as POST, handler as PUT, handler as PATCH, handler as DELETE };
