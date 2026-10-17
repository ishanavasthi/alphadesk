import React, { useState } from "react";
import { createRoot } from "react-dom/client";
import { ThemeBootstrap } from "@/components/shell/ThemeBootstrap";
import { ThemeToggle } from "@/components/portfolio/ThemeToggle";
import "@/app/globals.css";
import "@/app/portfolio/portfolio.css";

function Fixture() {
  const [route, setRoute] = useState(0);
  return (
    <div key={route} id="adp-root" data-adp style={{ minHeight: "150vh" }}>
      <ThemeBootstrap />
      <ThemeToggle />
      <button onClick={() => setRoute(route + 1)}>Remount surface</button>
      <p>Scrollable themed surface</p>
    </div>
  );
}

createRoot(document.getElementById("root")!).render(<Fixture />);
