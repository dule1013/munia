"use client";

import { useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { useUser } from "@clerk/nextjs";
import { portalApi } from "@/lib/api-client";
import { usePortalMode } from "@/components/portal-mode-provider";

export function CandidateGate({ children }: { children: React.ReactNode }) {
  const portalEnabled = usePortalMode();
  const { isLoaded, isSignedIn, user } = useUser();
  const pathname = usePathname();
  const router = useRouter();
  const [ready, setReady] = useState(false);
  const [error, setError] = useState("");
  const authPage = pathname.startsWith("/sign-in") || pathname.startsWith("/sign-up");

  useEffect(() => {
    if (!portalEnabled || !isLoaded || !isSignedIn || !user || authPage) return;
    let cancelled = false;
    if (!user.primaryEmailAddress?.emailAddress) return;
    portalApi.bootstrap()
      .then(() => portalApi.profile())
      .then((profile) => {
        if (cancelled) return;
        if (!profile.onboarding_complete && pathname !== "/onboarding") router.replace("/onboarding");
        else if (profile.onboarding_complete && pathname === "/onboarding") router.replace("/");
        setReady(true);
      })
      .catch((reason) => setError(reason instanceof Error ? reason.message : "Your workspace is unavailable"));
    return () => { cancelled = true; };
  }, [authPage, isLoaded, isSignedIn, pathname, portalEnabled, router, user]);

  if (!portalEnabled || authPage) return children;
  if (error) return <div className="flex min-h-screen items-center justify-center px-6 text-center text-sm text-danger">{error}</div>;
  if (!isLoaded || !isSignedIn || !ready) return <div className="flex min-h-screen items-center justify-center text-sm text-muted-foreground">Loading your workspace…</div>;
  return children;
}
