"use client";

import { createContext, useContext } from "react";

const PortalModeContext = createContext<boolean | null>(null);

export function PortalModeProvider({ enabled, children }: { enabled: boolean; children: React.ReactNode }) {
  return <PortalModeContext.Provider value={enabled}>{children}</PortalModeContext.Provider>;
}

export function usePortalMode(): boolean {
  const enabled = useContext(PortalModeContext);
  if (enabled === null) throw new Error("PortalModeProvider is missing");
  return enabled;
}
