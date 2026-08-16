import { BrokersSection } from "@/components/landing/BrokersSection";
import { FeaturesBento } from "@/components/landing/FeaturesBento";
import { FinalCta } from "@/components/landing/FinalCta";
import { HeroSection } from "@/components/landing/HeroSection";
import { HowItWorks } from "@/components/landing/HowItWorks";
import { LabSection } from "@/components/landing/LabSection";
import { TrustBand } from "@/components/landing/TrustBand";

/**
 * The public landing, built to the locked "Zinc Prospectus" design
 * (`docs/design/landing/c-prospectus.html`).
 *
 * It composes the sections in `components/landing/` and stays the component the
 * marketing page renders, with the same `authEnabled` contract: the flag gates
 * the waitlist CTA in both the hero and the closing block, because `/waitlist`
 * is a Clerk route that 404s until sign-in is switched on. Flag off, the live
 * demo is the single public entry point.
 *
 * Every colour resolves through the DECISION tokens on the `[data-adp]`
 * wrapper, so the whole page follows the dashboard's light and dark variants
 * with no theme branch of its own.
 */
export function LandingHero({ authEnabled }: { authEnabled: boolean }) {
  return (
    <main>
      <div className="mx-auto max-w-[1120px] px-4 sm:px-6">
        <HeroSection authEnabled={authEnabled} />
      </div>
      <TrustBand />
      <div className="mx-auto max-w-[1120px] px-4 sm:px-6">
        <FeaturesBento />
        <HowItWorks />
        <LabSection />
        <BrokersSection />
        <FinalCta authEnabled={authEnabled} />
      </div>
    </main>
  );
}
