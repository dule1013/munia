import { LayoutDashboard, Compass, ListChecks, Send, Radar, BarChart3, FileText, Settings, Satellite } from "lucide-react";
import type { ComponentType, SVGProps } from "react";

// Single source of truth for the app's primary destinations — shared by the
// desktop sidebar and the mobile nav so they can never drift.
export type NavItem = {
  href: string;
  label: string;
  icon: ComponentType<SVGProps<SVGSVGElement>>;
  chip?: string;
};

export const NAV_ITEMS: NavItem[] = [
  { href: "/", label: "Today", icon: LayoutDashboard },
  { href: "/explore", label: "Explore", icon: Compass, chip: "New" },
  { href: "/discovery", label: "Discovery", icon: Satellite },
  { href: "/pipeline", label: "Pipeline", icon: ListChecks },
  { href: "/followups", label: "Follow-ups", icon: Send },
  { href: "/portals", label: "Portals", icon: Radar },
  { href: "/analytics", label: "Analytics", icon: BarChart3 },
  { href: "/cv", label: "CV", icon: FileText },
  { href: "/config", label: "Config", icon: Settings },
];

export function navItemsForMode(portalEnabled: boolean): NavItem[] {
  // Discovery/Sources (LinkedIn, Watchlist, per-candidate metrics) is a
  // portal-mode-only concept — the single-user local CLI mode already has
  // its own /portals (portals.yml health) and /explore (ad-hoc scan) pages.
  if (!portalEnabled) return NAV_ITEMS.filter(({ href }) => href !== "/discovery");
  return NAV_ITEMS.filter(({ href }) => href !== "/followups" && href !== "/portals");
}

export function isActivePath(href: string, pathname: string): boolean {
  return href === "/" ? pathname === "/" : pathname.startsWith(href);
}
