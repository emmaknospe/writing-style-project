import { useState } from "react";
import type { Brief, BriefPoint } from "../types";
import { addSection, deleteSection, reorderSections, updateSection } from "../api";

/**
 * The proposed outline, editable before a word is drafted.
 *
 * Every edit goes through the ordinary section endpoints and then refetches, so
 * what gets approved is exactly what the server holds -- there is no local copy
 * of the outline to drift out of sync with it.
 */
export default function OutlineSidebar({
  brief,
  busy,
  onChanged,
  onApprove,
}: {
  brief: Brief;
  busy: boolean;
  onChanged: () => Promise<void>;
  onApprove: () => void;
}) {
  const [editingId, setEditingId] = useState<string | null>(null);
  const [draftHeading, setDraftHeading] = useState("");
  const [newHeading, setNewHeading] = useState("");
  const [saving, setSaving] = useState(false);

  async function run(action: () => Promise<unknown>) {
    setSaving(true);
    try {
      await action();
      await onChanged();
    } finally {
      setSaving(false);
    }
  }

  function startEdit(point: BriefPoint) {
    setEditingId(point.id);
    setDraftHeading(point.heading ?? "");
  }

  async function commitEdit(id: string) {
    const heading = draftHeading.trim();
    setEditingId(null);
    if (heading) await run(() => updateSection(id, { heading }));
  }

  async function move(index: number, delta: number) {
    const ids = brief.points.map((p) => p.id);
    const target = index + delta;
    if (target < 0 || target >= ids.length) return;
    [ids[index], ids[target]] = [ids[target], ids[index]];
    await run(() => reorderSections(brief.speech_id, ids));
  }

  const disabled = busy || saving;

  return (
    <div className="sidebar-inner">
      <h2>Proposed outline</h2>
      <p className="sidebar-note">
        Edit freely — nothing is drafted until you approve.
      </p>

      <ol className="outline">
        {brief.points.map((point, i) => (
          <li key={point.id} className="outline-point">
            <div className="outline-head">
              {editingId === point.id ? (
                <input
                  autoFocus
                  value={draftHeading}
                  onChange={(e) => setDraftHeading(e.target.value)}
                  onBlur={() => commitEdit(point.id)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") commitEdit(point.id);
                    if (e.key === "Escape") setEditingId(null);
                  }}
                />
              ) : (
                <span className="outline-heading">{point.heading}</span>
              )}
              <span className="outline-actions">
                <button
                  type="button"
                  disabled={disabled || i === 0}
                  onClick={() => move(i, -1)}
                  title="Move up"
                >
                  ↑
                </button>
                <button
                  type="button"
                  disabled={disabled || i === brief.points.length - 1}
                  onClick={() => move(i, 1)}
                  title="Move down"
                >
                  ↓
                </button>
                <button
                  type="button"
                  disabled={disabled}
                  onClick={() => startEdit(point)}
                  title="Rename"
                >
                  ✎
                </button>
                <button
                  type="button"
                  disabled={disabled}
                  onClick={() => run(() => deleteSection(point.id))}
                  title="Remove"
                >
                  ✕
                </button>
              </span>
            </div>
            {point.intent && <p className="outline-rationale">{point.intent}</p>}
          </li>
        ))}
      </ol>

      <form
        className="outline-add"
        onSubmit={(e) => {
          e.preventDefault();
          const heading = newHeading.trim();
          if (!heading) return;
          setNewHeading("");
          run(() => addSection(brief.speech_id, heading));
        }}
      >
        <input
          value={newHeading}
          onChange={(e) => setNewHeading(e.target.value)}
          placeholder="Add a point…"
          disabled={disabled}
        />
        <button type="submit" disabled={disabled || !newHeading.trim()}>
          +
        </button>
      </form>

      {brief.gaps.length > 0 && (
        <div className="sidebar-gaps">
          <h3>Gaps in the corpus</h3>
          <ul>
            {brief.gaps.map((g, i) => (
              <li key={i}>{g}</li>
            ))}
          </ul>
        </div>
      )}

      <button
        type="button"
        className="approve"
        disabled={disabled || brief.points.length === 0}
        onClick={onApprove}
      >
        Approve &amp; draft
      </button>
    </div>
  );
}
