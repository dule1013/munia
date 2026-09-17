import "server-only";
import { auth } from "@clerk/nextjs/server";

const API_URL = process.env.CAREER_OPS_API_URL || "http://127.0.0.1:8000";

export async function serverApi<T>(path: string, init?: RequestInit): Promise<T> {
  const session = await auth();
  if (!session.userId) session.redirectToSignIn();
  const token = await session.getToken();
  const response = await fetch(new URL(`/api/v1${path}`, API_URL), { ...init, headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json", ...init?.headers }, cache: "no-store" });
  if (!response.ok) throw new Error(`Career Ops API ${response.status}`);
  return response.json() as Promise<T>;
}
