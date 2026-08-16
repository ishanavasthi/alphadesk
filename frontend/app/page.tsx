import { redirect } from "next/navigation";

/**
 * The research desk moved to `/lab` in card F4 (it is a labelled *simulation*,
 * kept distinct from the real per-user portfolio at `/portfolio`). Nothing lives
 * at the root yet — card U1 owns the app shell and the landing. Until then `/`
 * redirects to the desk so existing links and the old bookmark keep working.
 */
export default function Home() {
  redirect("/lab");
}
