import type { Metadata, Viewport } from "next";
import type { ReactNode } from "react";
import { JetBrains_Mono, Newsreader } from "next/font/google";
import { Providers } from "@/components/Providers";
import "./globals.css";

const newsreader = Newsreader({
  subsets: ["latin"],
  weight: "variable",
  variable: "--font-newsreader",
  display: "swap",
});
const jetbrains = JetBrains_Mono({ subsets: ["latin"], variable: "--font-jetbrains", display: "swap" });

const TITLE = "TaskBridge — Claude plans. OpenCode builds.";
const DESCRIPTION =
  "Dispatch real coding work from Claude to headless OpenCode agents via a durable SQLite queue.";

export const metadata: Metadata = {
  metadataBase: new URL(process.env.URL ?? "https://taskbridge-landing-page.netlify.app"),
  title: TITLE,
  description: DESCRIPTION,
  openGraph: {
    title: TITLE,
    description: DESCRIPTION,
    type: "website",
    siteName: "TaskBridge",
  },
  twitter: { card: "summary_large_image", title: TITLE, description: DESCRIPTION },
};

export const viewport: Viewport = {
  themeColor: "#100c08",
};

export default function RootLayout({ children }: Readonly<{ children: ReactNode }>) {
  return (
    <html lang="en" suppressHydrationWarning className={`${newsreader.variable} ${jetbrains.variable}`}>
      <head>
        {/* Set the theme before paint so there's no flash of the wrong ground colour. */}
        <script
          dangerouslySetInnerHTML={{
            __html: `(function(){try{var t=localStorage.getItem('taskbridge-theme');if(t!=='light'&&t!=='dark'){t=window.matchMedia('(prefers-color-scheme: light)').matches?'light':'dark';}document.documentElement.setAttribute('data-theme',t);}catch(e){document.documentElement.setAttribute('data-theme','dark');}})()`,
          }}
        />
      </head>
      <body>
        <a
          href="#main"
          className="sr-only focus:not-sr-only focus:fixed focus:top-3 focus:left-3 focus:z-[70] focus:bg-panel focus:px-3 focus:py-2 focus:font-mono focus:text-[12px]"
        >
          Skip to content
        </a>
        <Providers>{children}</Providers>
        <div className="grain" aria-hidden="true" />
      </body>
    </html>
  );
}
