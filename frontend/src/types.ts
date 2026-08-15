// Mirrors api/app/schemas.py. Keep the two in sync.

export type BriefStatus = "researching" | "outline_proposed" | "drafting" | "ready";

export interface SectionSource {
  id: string;
  qdrant_point_id: string;
  quoted_text: string;
  title: string | null;
  speaker: string | null;
  date: string | null;
  category: string | null;
  /** "first-person" | "mixed" | "third-party" — whether the words are hers.
   *  Surfaced in the UI because a quote pulled from a staff-written press
   *  release is not the same claim as one from a delivered speech. */
  voice: string | null;
  source_url: string | null;
  position: number;
}

export interface SectionWebSource {
  id: string;
  url: string;
  title: string | null;
  claim: string | null;
  position: number;
}

/** A talking point. `text` is empty while the outline awaits approval. */
export interface BriefPoint {
  id: string;
  position: number;
  heading: string | null;
  text: string;
  intent: string | null;
  sources: SectionSource[];
  web_sources: SectionWebSource[];
}

export interface BriefMessage {
  id: string;
  role: string;
  content: string;
  position: number;
  created_at: string;
}

export interface Brief {
  speech_id: string;
  title: string;
  event_prompt: string;
  status: BriefStatus;
  event_summary: string | null;
  framing: string | null;
  likely_questions: string[];
  gaps: string[];
  points: BriefPoint[];
  messages: BriefMessage[];
  created_at: string;
  updated_at: string;
}

export interface BriefSummary {
  speech_id: string;
  title: string;
  event_prompt: string;
  status: BriefStatus;
  created_at: string;
  updated_at: string;
}

/** One line of the live activity feed, from an `activity` SSE event. */
export interface Activity {
  kind: "corpus_search" | "corpus_result" | "web_search" | "web_result";
  query?: string;
  count?: number;
}
