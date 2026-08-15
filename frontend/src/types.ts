// Mirrors api/app/schemas.py. Keep the two in sync.

export interface CorpusCitation {
  quote: string;
  title: string;
  date: string;
  source_url: string;
}

export interface WebCitation {
  claim: string;
  title: string;
  url: string;
}

export interface TalkingPoint {
  headline: string;
  talking_point: string;
  corpus_support: CorpusCitation[];
  web_context: WebCitation[];
}

export interface TalkingPointsBrief {
  event_summary: string;
  framing: string;
  points: TalkingPoint[];
  likely_questions: string[];
  gaps: string[];
}
