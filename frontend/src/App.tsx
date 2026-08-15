import { useState } from "react";
import type { TalkingPointsBrief } from "./types";
import { generateBrief } from "./api";
import BriefView from "./components/BriefView";
import "./App.css";

const PLACEHOLDER = `Ribbon-cutting at a new battery plant in Danville next week.
About 200 workers on site, plant management and local officials attending,
press availability afterwards.`;

export default function App() {
  const [prompt, setPrompt] = useState("");
  const [brief, setBrief] = useState<TalkingPointsBrief | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isGenerating, setIsGenerating] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const text = prompt.trim();
    if (!text || isGenerating) return;

    setIsGenerating(true);
    setError(null);
    setBrief(null);

    try {
      setBrief(await generateBrief(text));
    } catch (err) {
      setError(
        err instanceof DOMException && err.name === "AbortError"
          ? "The brief took too long to generate. Try a shorter event description."
          : "Could not generate the brief. Check the API logs and try again."
      );
    } finally {
      setIsGenerating(false);
    }
  }

  return (
    <div className="app">
      <header className="app-header">
        <h1>Event talking points</h1>
        <p className="app-subtitle">
          Describe an upcoming event. The brief draws on Abigail Spanberger&rsquo;s prior
          remarks and on current information from the web.
        </p>
      </header>

      <form className="prompt-form" onSubmit={handleSubmit}>
        <label htmlFor="event-prompt">Event description</label>
        <textarea
          id="event-prompt"
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          placeholder={PLACEHOLDER}
          rows={5}
          disabled={isGenerating}
        />
        <button type="submit" disabled={isGenerating || !prompt.trim()}>
          {isGenerating ? "Generating…" : "Generate brief"}
        </button>
      </form>

      {isGenerating && (
        <p className="status" role="status">
          Searching the corpus and the web. This usually takes under a minute.
        </p>
      )}

      {error && (
        <p className="status status-error" role="alert">
          {error}
        </p>
      )}

      {brief && <BriefView brief={brief} />}
    </div>
  );
}
