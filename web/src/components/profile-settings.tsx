"use client";

import { useState } from "react";
import type { CandidateProfile } from "@/lib/api-client";
import { portalApi } from "@/lib/api-client";

export function ProfileSettings({ candidate }: { candidate: CandidateProfile }) {
  const [profile, setProfile] = useState(candidate.profile);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const candidateData = (profile.candidate || {}) as Record<string, unknown>;
  const targets = (profile.target_roles || {}) as Record<string, unknown>;
  const authorization = (profile.authorization || {}) as Record<string, unknown>;
  const preferences = (profile.preferences || {}) as Record<string, unknown>;
  const compensation = (profile.compensation || {}) as Record<string, unknown>;

  const update = (section: string, field: string, value: unknown) => setProfile((current) => ({ ...current, [section]: { ...((current[section] || {}) as Record<string, unknown>), [field]: value } }));
  const csv = (value: unknown) => Array.isArray(value) ? value.join(", ") : "";

  async function save() {
    setSaving(true);
    await portalApi.saveProfile(profile);
    setSaving(false);
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  }

  return (
    <div className="mx-auto w-full max-w-[120rem] px-6 py-10 lg:px-8">
      <h1 className="font-sans font-semibold text-3xl tracking-tight text-landing">Profile and search preferences</h1>
      <p className="mt-2 text-sm text-muted-foreground">These candidate-specific settings drive discovery, triage, and evaluation.</p>
      <div className="mt-8 grid gap-5 sm:grid-cols-2">
        <Field label="Name" value={String(candidateData.full_name || candidate.user.name)} onChange={(value) => update("candidate", "full_name", value)} />
        <Field label="Current location" value={String(candidateData.location || "")} onChange={(value) => update("candidate", "location", value)} />
        <Field label="Target roles" value={csv(targets.primary)} onChange={(value) => update("target_roles", "primary", value.split(",").map((item) => item.trim()).filter(Boolean))} />
        <Field label="Work authorization" value={csv(authorization.work_authorization)} onChange={(value) => update("authorization", "work_authorization", value.split(",").map((item) => item.trim()).filter(Boolean))} />
        <Field label="Remote preference" value={String(preferences.remote || "")} onChange={(value) => update("preferences", "remote", value)} />
        <Field label="Relocation preference" value={String(preferences.relocation || "")} onChange={(value) => update("preferences", "relocation", value)} />
        <Field label="Compensation" value={String(compensation.expectation || compensation.target_range || "")} onChange={(value) => update("compensation", "expectation", value)} />
      </div>
      <label className="mt-5 flex items-center gap-2 text-sm"><input type="checkbox" checked={Boolean(authorization.sponsorship_required)} onChange={(event) => update("authorization", "sponsorship_required", event.target.checked)} /> Sponsorship required</label>
      <button onClick={save} disabled={saving} className="mt-8 rounded-lg bg-brand px-5 py-2.5 text-sm font-semibold text-white disabled:opacity-50">{saving ? "Saving…" : saved ? "Saved" : "Save profile"}</button>
    </div>
  );
}

function Field({ label, value, onChange }: { label: string; value: string; onChange: (value: string) => void }) {
  return <label><span className="mb-2 block text-sm font-medium">{label}</span><input value={value} onChange={(event) => onChange(event.target.value)} className="w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm outline-none focus:border-brand" /></label>;
}
