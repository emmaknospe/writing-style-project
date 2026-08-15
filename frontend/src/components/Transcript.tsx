import { useEffect, useRef } from "react";
import type { Activity, BriefMessage } from "../types";

function activityLine(a: Activity): string {
  switch (a.kind) {
    case "corpus_search":
      return `searching her remarks — “${a.query}”`;
    case "corpus_result":
      return `${a.count} passage${a.count === 1 ? "" : "s"}`;
    case "web_search":
      return `searching the web — “${a.query}”`;
    case "web_result":
      return `${a.count} result${a.count === 1 ? "" : "s"}`;
  }
}

export default function Transcript({
  messages,
  activity,
  isRunning,
}: {
  messages: BriefMessage[];
  activity: Activity[];
  isRunning: boolean;
}) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, activity]);

  return (
    <div className="transcript">
      {messages.map((m) => (
        <div key={m.id} className={`msg msg-${m.role}`}>
          {m.content}
        </div>
      ))}

      {activity.length > 0 && (
        <ul className="activity" aria-live="polite">
          {activity.map((a, i) => (
            <li key={i} className={`activity-${a.kind}`}>
              {activityLine(a)}
            </li>
          ))}
        </ul>
      )}

      {isRunning && <p className="working">working…</p>}
      <div ref={bottomRef} />
    </div>
  );
}
