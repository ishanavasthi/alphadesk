import type { Metadata } from "next";
import type { ReactNode } from "react";
import { Inter, IBM_Plex_Mono } from "next/font/google";
import "./globals.css";
import { TopBar } from "@/components/TopBar";

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
        <TopBar />
        {children}
      </body>
    </html>
  );
}
