export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
}

export interface ChatApiResponse {
  reply: string;
  session_id: string;
}
