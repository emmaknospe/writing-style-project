import { useEffect, useState } from "react";
import type { Activity, Brief } from "./types";
import {
  approveOutline,
  createBrief,
  getBrief,
  sendMessage as postMessage,
} from "./api";
import Transcript from "./components/Transcript";
import OutlineSidebar from "./components/OutlineSidebar";
import BriefSidebar from "./components/BriefSidebar";
import "./App.css";

const PLACEHOLDER = `Ribbon-cutting at a new battery plant in Danville next week.
About 200 workers on site, plant management and local officials attending,
press availability afterwards.`;

export default function App() {
  const [brief, setBrief] = useState<Brief | null>(null);
  const [input, setInput] = useState("");
  const [activity, setActivity] = useState<Activity[]>([]);
  const [isRunning, setIsRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Resume the most recent brief on load. Briefs live in SQLite, so a reload
  // (or an api restart) doesn't lose the session.
  useEffect(() => {
    const id = localStorage.getItem("briefId");
    if (id) getBrief(id).then(setBrief).catch(() => localStorage.removeItem("briefId"));
  }, []);

  function handlers() {
    return {
      onActivity: (a: Activity) => setActivity((prev) => [...prev, a]),
      onBrief: (b: Brief) => {
        setBrief(b);
        setActivity([]);
      },
      onError: (detail: string) => setError(detail),
    };
  }

  async function start(prompt: string) {
    setError(null);
    setIsRunning(true);
    try {
      const created = await createBrief(prompt);
      localStorage.setItem("briefId", created.speech_id);
      setBrief(created);
      await postMessage(created.speech_id, "Research this and propose an outline.", handlers());
    } finally {
      setIsRunning(false);
    }
  }

  async function send(message: string) {
    if (!brief) return;
    setError(null);
    setIsRunning(true);
    // Show the message immediately; the refetch after the run replaces it with
    // the server's copy.
    setBrief({
      ...brief,
      messages: [
        ...brief.messages,
        {
          id: `local-${Date.now()}`,
          role: "user",
          content: message,
          position: brief.messages.length,
          created_at: new Date().toISOString(),
        },
      ],
    });
    try {
      await postMessage(brief.speech_id, message, handlers());
    } finally {
      setIsRunning(false);
    }
  }

  async function approve() {
    if (!brief) return;
    setError(null);
    setIsRunning(true);
    try {
      await approveOutline(brief.speech_id, handlers());
    } finally {
      setIsRunning(false);
    }
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    const text = input.trim();
    if (!text || isRunning) return;
    setInput("");
    if (brief) await send(text);
    else await start(text);
  }

  const refresh = async () => {
    if (brief) setBrief(await getBrief(brief.speech_id));
  };

  return (
    <div className="app">
      <header className="app-header">
        <h1>Event talking points</h1>
        <p className="app-subtitle">
          Describe an event. The agent researches it, proposes an outline for you to
          edit, and drafts talking points only once you approve.
        </p>
        {brief && (
          <button
            type="button"
            className="new-brief"
            onClick={() => {
              localStorage.removeItem("briefId");
              setBrief(null);
              setActivity([]);
            }}
          >
            New brief
          </button>
        )}
      </header>

      <main className="panes">
        <section className="pane pane-chat">
          <Transcript
            messages={brief?.messages ?? []}
            activity={activity}
            isRunning={isRunning}
          />

          {error && (
            <p className="status status-error" role="alert">
              {error}
            </p>
          )}

          <form className="composer" onSubmit={submit}>
            <textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder={brief ? "Ask for a change…" : PLACEHOLDER}
              rows={brief ? 2 : 5}
              disabled={isRunning}
              onKeyDown={(e) => {
                if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) submit(e);
              }}
            />
            <button type="submit" disabled={isRunning || !input.trim()}>
              {isRunning ? "Working…" : brief ? "Send" : "Start"}
            </button>
          </form>
        </section>

        <aside className="pane pane-sidebar">
          {!brief && <p className="sidebar-empty">The outline will appear here.</p>}
          {brief && brief.status === "researching" && (
            <p className="sidebar-empty">Researching the event…</p>
          )}
          {brief && brief.status === "outline_proposed" && (
            <OutlineSidebar
              brief={brief}
              busy={isRunning}
              onChanged={refresh}
              onApprove={approve}
            />
          )}
          {brief && (brief.status === "drafting" || brief.status === "ready") && (
            <BriefSidebar brief={brief} />
          )}
        </aside>
      </main>
    </div>
  );
}
