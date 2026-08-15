import type { TalkingPointsBrief } from "./types";

// A brief runs several corpus searches plus up to WEB_SEARCH_MAX_USES web
// searches before the model writes anything, so these requests are long-lived.
// nginx is configured to allow 300s (see frontend/nginx.conf); the client gives
// up slightly sooner so the user sees our error rather than a proxy timeout.
const REQUEST_TIMEOUT_MS = 290_000;

export async function generateBrief(prompt: string): Promise<TalkingPointsBrief> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);

  try {
    const res = await fetch("/api/talking-points", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ prompt }),
      signal: controller.signal,
    });
    if (!res.ok) {
      throw new Error(`Brief request failed: ${res.status}`);
    }
    return res.json();
  } finally {
    clearTimeout(timeout);
  }
}
