import { ProfileSettings } from "@/components/profile-settings";
import { ConfigForm } from "@/components/config-form";
import { serverApi } from "@/lib/api-server";
import type { CandidateProfile } from "@/lib/api-client";
import { portalMode } from "@/lib/portal-mode.mjs";

export const dynamic = "force-dynamic";

export default async function ConfigPage() {
  if (!portalMode()) return <ConfigForm />;
  return <ProfileSettings candidate={await serverApi<CandidateProfile>("/candidate/profile")} />;
}
