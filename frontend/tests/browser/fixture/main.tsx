import React from "react";
import { createRoot } from "react-dom/client";
import { TopMovers } from "@/components/portfolio/TopMovers";
import { toggleAmountsHidden } from "@/components/portfolio/privacy";
import "@/app/globals.css";
import "@/app/portfolio/portfolio.css";

// Real component, styles and portfolio shell dimensions; no Clerk or backend.
createRoot(document.getElementById("root")!).render(
  <div data-adp data-adp-theme={new URLSearchParams(location.search).get("theme")} className="min-h-screen bg-background text-foreground">
    <div className="mx-auto max-w-[1120px] px-4 pb-16 sm:px-6">
      <button onClick={toggleAmountsHidden}>Toggle amounts</button>
      <TopMovers />
    </div>
  </div>,
);
