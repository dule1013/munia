"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useUser } from "@clerk/nextjs";
import { portalApi } from "@/lib/api-client";

export function OnboardingForm() {
  const { user } = useUser();
  const router = useRouter();
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true);
    setError("");
    const data = new FormData(event.currentTarget);
    try {
      await portalApi.onboard({
        name: String(data.get("name") || ""),
        master_cv: String(data.get("master_cv") || ""),
        target_roles: String(data.get("target_roles") || "").split(",").map((value) => value.trim()).filter(Boolean),
        current_location: String(data.get("current_location") || ""),
        work_authorization: String(data.get("work_authorization") || "").split(",").map((value) => value.trim()).filter(Boolean),
        sponsorship_required: data.get("sponsorship_required") === "on",
        remote_preference: String(data.get("remote_preference") || ""),
        relocation_preference: String(data.get("relocation_preference") || ""),
        compensation: { expectation: String(data.get("compensation") || "") },
      });
      router.replace("/");
      router.refresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not save profile");
      setSaving(false);
    }
  }

  return (
    <main className="mx-auto w-full max-w-[120rem] px-6 py-10 lg:px-8">
      <h1 className="font-display text-3xl tracking-tight text-landing">Set up your job search</h1>
      <p className="mt-2 text-sm text-muted-foreground">Career Ops uses only the facts and preferences you provide here.</p>
      <form onSubmit={submit} className="mt-8 space-y-6">
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Name" name="name" defaultValue={user?.fullName || ""} required />
          <Field label="Email (managed by Clerk)" name="email" type="email" defaultValue={user?.primaryEmailAddress?.emailAddress || ""} disabled />
          <Field label="Target roles" name="target_roles" placeholder="Director of Engineering, Head of Engineering" required />
          <Field label="Current location" name="current_location" required />
          <Field label="Work authorization" name="work_authorization" placeholder="Spain, EU/EEA" required />
          <Field label="Remote preference" name="remote_preference" placeholder="Remote or hybrid" required />
          <Field label="Relocation preference" name="relocation_preference" placeholder="Open within EU" required />
          <Field label="Compensation expectations" name="compensation" placeholder="Currency and target range" required />
        </div>
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" name="sponsorship_required" /> Sponsorship required</label>
        <label className="block"><span className="mb-2 block text-sm font-medium">Paste your Master CV</span><textarea name="master_cv" required rows={18} className="w-full rounded-xl border border-border bg-surface p-4 font-mono text-sm outline-none focus:border-brand" /></label>
        {error && <p className="text-sm text-danger">{error}</p>}
        <button disabled={saving} className="rounded-lg bg-brand px-5 py-2.5 text-sm font-semibold text-white disabled:opacity-50">{saving ? "Saving…" : "Create workspace"}</button>
      </form>
    </main>
  );
}

function Field({ label, ...props }: React.InputHTMLAttributes<HTMLInputElement> & { label: string; name: string }) {
  return <label className="block"><span className="mb-2 block text-sm font-medium">{label}</span><input {...props} className="w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm outline-none focus:border-brand" /></label>;
}
