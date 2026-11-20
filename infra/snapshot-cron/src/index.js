// Cloudflare Worker entrypoint: cron triggers only, no HTTP surface
// (`workers_dev` and preview URLs are off in wrangler.jsonc).
import { runScheduled } from "./run.js";

export default {
  async scheduled(controller, env) {
    // Awaited, not waitUntil'd: a thrown error marks the invocation as failed
    // in Workers observability, which is where a broken night must show up.
    const result = await runScheduled(controller.cron, env);
    console.log("done", JSON.stringify(result));
  },
};
