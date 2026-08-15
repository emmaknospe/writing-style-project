import type { Activity, Brief, BriefSummary } from "./types";

// A run does several corpus searches plus up to WEB_SEARCH_MAX_USES web
// searches before the model writes anything, so these are long-lived. nginx
// allows 300s (see frontend/nginx.conf); the client gives up slightly sooner so
// the user sees our error rather than a proxy timeout.
const REQUEST_TIMEOUT_MS = 290_000;

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

export async function listBriefs(): Promise<BriefSummary[]> {
  return json(await fetch("/api/briefs"));
}

export async function getBrief(id: string): Promise<Brief> {
  return json(await fetch(`/api/briefs/${id}`));
}

export async function createBrief(prompt: string): Promise<Brief> {
  return json(
    await fetch("/api/briefs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ prompt }),
    })
  );
}

// --- outline editing: main's ordinary section endpoints ---------------------

export async function updateSection(id: string, patch: { heading?: string; intent?: string }) {
  return json(
    await fetch(`/api/sections/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(patch),
    })
  );
}

export async function deleteSection(id: string): Promise<void> {
  const res = await fetch(`/api/sections/${id}`, { method: "DELETE" });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
}

export async function addSection(speechId: string, heading: string) {
  return json(
    await fetch(`/api/speeches/${speechId}/sections`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ heading, text: "" }),
    })
  );
}

export async function reorderSections(speechId: string, sectionIds: string[]) {
  return json(
    await fetch(`/api/speeches/${speechId}/sections/order`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ section_ids: sectionIds }),
    })
  );
}

// --- the streamed runs ------------------------------------------------------

export interface StreamHandlers {
  onActivity(activity: Activity): void;
  onBrief(brief: Brief): void;
  onError(detail: string): void;
}

/**
 * Read an SSE response body.
 *
 * Hand-rolled rather than using `EventSource`, which only does GET: these runs
 * are POSTs carrying a message body. Frames are `event:`/`data:` pairs
 * separated by a blank line, so buffer until one is complete.
 */
async function readStream(res: Response, handlers: StreamHandlers): Promise<void> {
  if (!res.ok || !res.body) {
    handlers.onError(`${res.status} ${res.statusText}`);
    return;
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    let split: number;
    while ((split = buffer.indexOf("\n\n")) !== -1) {
      const frame = buffer.slice(0, split);
      buffer = buffer.slice(split + 2);

      let name = "message";
      const dataLines: string[] = [];
      for (const line of frame.split("\n")) {
        if (line.startsWith("event:")) name = line.slice(6).trim();
        else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
      }
      if (dataLines.length === 0) continue;

      const payload = JSON.parse(dataLines.join("\n"));
      if (name === "activity") handlers.onActivity(payload as Activity);
      else if (name === "outline" || name === "brief") handlers.onBrief(payload as Brief);
      else if (name === "error") handlers.onError(payload.detail ?? "unknown error");
    }
  }
}

async function post(path: string, body: unknown, handlers: StreamHandlers): Promise<void> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  try {
    const res = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: controller.signal,
    });
    await readStream(res, handlers);
  } catch (err) {
    handlers.onError(
      err instanceof DOMException && err.name === "AbortError"
        ? "That took too long. Try a shorter event description."
        : "The request failed. Check the API logs and try again."
    );
  } finally {
    clearTimeout(timeout);
  }
}

export function sendMessage(briefId: string, message: string, handlers: StreamHandlers) {
  return post(`/api/briefs/${briefId}/messages`, { message }, handlers);
}

export function approveOutline(briefId: string, handlers: StreamHandlers) {
  return post(`/api/briefs/${briefId}/approve`, undefined, handlers);
}
