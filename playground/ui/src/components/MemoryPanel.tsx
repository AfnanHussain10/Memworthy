// The memory store at one point in the conversation, grouped by type, with retired entries.
import type { MemoryItem } from "../api";
import { Empty } from "./bits";

interface Props {
  title: string;
  memories: MemoryItem[];
  archive: MemoryItem[];
  /** ids+text present one step earlier, to mark what just changed */
  before: Set<string> | null;
  /** text brought back by a rollback in this step: tagged "restored", not "new" */
  restored?: string | null;
  onRetiredClick?: (m: MemoryItem) => void;
}

export function MemoryPanel({ title, memories, archive, before, restored, onRetiredClick }: Props) {
  const groups = new Map<string, MemoryItem[]>();
  for (const m of memories) groups.set(m.type, [...(groups.get(m.type) ?? []), m]);
  return (
    <div className="memory">
      <p className="panel-sub">{title}</p>
      {memories.length === 0 && <Empty>Nothing remembered yet.</Empty>}
      {[...groups].map(([type, items]) => (
        <div key={type} className="mgroup">
          <h4>{type}</h4>
          {items.map((m) => {
            const fresh = before !== null && !before.has(`${m.id}|${m.text}`);
            return (
              <div key={m.id} className={`mem ${fresh ? "fresh" : ""}`}>
                {fresh && m.previous_text && <s className="was">{m.previous_text}</s>}
                <div className="mem-text">{m.text}
                  {m.labels.map((l) => <span key={l} className="label">{l}</span>)}
                  {fresh && <span className="new-tag">{m.text === restored ? "restored" : m.previous_text ? "changed" : "new"}</span>}
                </div>
                <div className="src">
                  from “{m.source}”{m.confidence != null && ` · ${Math.round(m.confidence * 100)}%`}
                </div>
              </div>
            );
          })}
        </div>
      ))}
      {archive.length > 0 && (
        <details className="retired">
          <summary>Retired ({archive.length})</summary>
          <p className="hint">Replaced or rolled back. Memworthy keeps them so a change can be undone.</p>
          {archive.map((m) => (
            <div key={m.id} className="mem retired-mem">
              <s>{m.text}</s>
              {onRetiredClick && <button className="link" onClick={() => onRetiredClick(m)}>which message retired it?</button>}
            </div>
          ))}
        </details>
      )}
    </div>
  );
}
