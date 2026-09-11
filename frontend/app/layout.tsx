import type { Metadata } from "next";
import type { ReactNode } from "react";
import { Inter, IBM_Plex_Mono } from "next/font/google";
import "./globals.css";
import { Identity } from "@/components/Identity";

const inter = Inter({ subsets: ["latin"], variable: "--font-inter" });
const mono = IBM_Plex_Mono({
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
  variable: "--font-mono",
});

export const metadata: Metadata = {
  title: "AlphaDesk",
  description:
    "One honest view of an Indian portfolio, plus a labelled multi-agent research simulation. Descriptive analytics only; not investment advice.",
};

export default function RootLayout({
  children,
}: Readonly<{ children: ReactNode }>) {
  return (
    <html lang="en" className={`${inter.variable} ${mono.variable}`}>
      <body className="min-h-screen font-sans antialiased">
        <Identity>
          {/* Two things live per surface, not here:

              1. **Chrome.** Card U1 owns one clean mechanism and it is
                 declarative per surface, not a root-level conditional: the
                 `SiteHeader` is rendered by the marketing group and `/demo`,
                 `/portfolio` carries its own `PortfolioTopBar`, and `/lab` its
                 `LabTopBar`. This replaced the interim `TerminalChrome`. Since
                 issue #18 all three wear the same DECISION tokens; they differ
                 in what they *hold*, not in how they look.

              2. **`AuthProvider`** (the IND Money link state — "has the desk been
                 linked to a broker?", distinct from `Identity`'s "who is looking
                 at it?"). It is **not** global, because mounting it here made its
                 warm-up ping (`/auth/status`) fire on every page — including the
                 public `/demo`, whose whole guarantee is that it touches no
                 authenticated endpoint. It now wraps only the surfaces that read
                 `useIndMoney`: the Lab (`app/lab/layout`) and the flag-on landing
                 (`app/(marketing)/page`). */}
          {children}
        </Identity>
      </body>
    </html>
  );
}
