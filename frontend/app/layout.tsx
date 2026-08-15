import type { Metadata } from "next";
import type { ReactNode } from "react";
import { Inter, IBM_Plex_Mono } from "next/font/google";
import "./globals.css";
import { AuthProvider } from "@/components/AuthProvider";
import { Identity } from "@/components/Identity";
import { TerminalChrome } from "@/components/TerminalChrome";

const inter = Inter({ subsets: ["latin"], variable: "--font-inter" });
const mono = IBM_Plex_Mono({
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
  variable: "--font-mono",
});

export const metadata: Metadata = {
  title: "AlphaDesk - NSE Research Terminal",
  description:
    "Multi-agent Indian equity research desk. Type a thesis; the desk scans, researches, and reviews - you approve.",
};

export default function RootLayout({
  children,
}: Readonly<{ children: ReactNode }>) {
  return (
    <html lang="en" className={`dark ${inter.variable} ${mono.variable}`}>
      <body className="min-h-screen font-sans antialiased">
        <Identity>
          {/* Distinct from `Identity` above and deliberately so: this one
              answers "has the desk been linked to a broker?", not "who is
              looking at it?". Its hook is `useIndMoney` for that reason. */}
          <AuthProvider>
            {/* The terminal chrome belongs to the Bloomberg-styled research desk
                (`/`, `/a/[id]`). The D1 portfolio surface renders its own shadcn
                top bar, so the two must not stack. Interim: card U1 takes
                ownership of one app shell and deletes this component. */}
            <TerminalChrome />
            {children}
          </AuthProvider>
        </Identity>
      </body>
    </html>
  );
}
