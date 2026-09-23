import { ClerkProvider } from "@clerk/nextjs";
import type { Metadata, Viewport } from "next";
import { inter, instrumentSerif, instrumentSerifItalic } from "@/lib/fonts";
import { AppShell } from "@/components/app-shell";
import { CandidateGate } from "@/components/candidate-gate";
import { PortalModeProvider } from "@/components/portal-mode-provider";
import { portalMode } from "@/lib/portal-mode.mjs";
import "./globals.css";

export const metadata: Metadata = {
  title: "career-ops — official web experience",
  description: "The official, local-first web experience for career-ops.",
  // Home-screen / standalone (iOS): let our theme-color flow up to the status bar
  // + Dynamic Island; safe-area insets handle the layout.
  appleWebApp: { capable: true, statusBarStyle: "black-translucent", title: "career-ops" },
};

export const viewport: Viewport = {
  // viewport-fit=cover → env(safe-area-inset-*) become non-zero so the header can
  // sit flush under the notch / Dynamic Island.
  viewportFit: "cover",
  // Default (corrected to the real theme before paint by THEME_SCRIPT, then kept
  // in sync by the theme toggle). Dark flows seamlessly into the black island.
  themeColor: "#1a1a1a",
};

// Before paint: set the theme class AND tint the browser chrome (theme-color) to
// match — so Safari's status bar / URL bar unify with the header instead of a
// jarring light seam. Matches --bg (light #fafafa / dark #1a1a1a).
const THEME_SCRIPT = `(function(){try{var t=localStorage.getItem('career-ops:theme');var d=t==='dark'||(!t&&window.matchMedia('(prefers-color-scheme: dark)').matches);if(d)document.documentElement.classList.add('dark');var m=document.querySelector('meta[name="theme-color"]');if(!m){m=document.createElement('meta');m.setAttribute('name','theme-color');document.head.appendChild(m);}m.setAttribute('content',d?'#1a1a1a':'#fafafa');}catch(e){document.documentElement.classList.add('dark');}})();`;

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html
      lang="en"
      suppressHydrationWarning
      className={`${inter.variable} ${instrumentSerif.variable} ${instrumentSerifItalic.variable}`}
    >
      <body className="font-sans antialiased">
        <ClerkProvider>
          <script dangerouslySetInnerHTML={{ __html: THEME_SCRIPT }} />
          <PortalModeProvider enabled={portalMode()}><CandidateGate><AppShell>{children}</AppShell></CandidateGate></PortalModeProvider>
        </ClerkProvider>
      </body>
    </html>
  );
}
