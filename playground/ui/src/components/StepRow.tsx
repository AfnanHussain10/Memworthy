// One timeline row: the message, the verdict and its effect on memory; "Why?" opens the explanation.
import type { Decision, PolicySummary, Thresholds } from "../api";
import { verdict, whySentence } from "../labels";
import { Explanation } from "./Explanation";
import { ModeTag, Verdict } from "./bits";

interface Props {
  n: number;
  message: string;
  d: Decision;
  was: Decision | null;
  caption: string | null;
  selected: boolean;
  open: boolean;
  onSelect: () => void;
  onToggle: () => void;
  thresholds: Thresholds;
  summary: PolicySummary;
  onShowRule: (id: string) => void;
}

export function Effect({ d }: { d: Decision }) {
  if (d.mode === "needs-live") return <span className="effect muted">Held for review until a live judge answers</span>;
  if (d.patch) {
    return (
      <span className="effect">
        <s>{d.patch.old_text}</s> <span aria-hidden="true">→</span><span className="sr-only">becomes</span> {d.patch.new_text}
      </span>
    );
  }
  switch (d.action) {
    case "store":
    case "store_labeled":
      return <span className="effect"><span className="plus">+</span> {d.text}{d.labels.map((l) => <span key={l} className="label">{l}</span>)}</span>;
    case "redact":
      return <span className="effect"><span className="plus">+</span> {d.redacted_text ?? d.text}</span>;
    case "merge":
    case "supersede":
      return <span className="effect"><s>{d.target}</s> retired</span>;
    case "review":
      return <span className="effect muted">Held for a person to check</span>;
    default:
      return <span className="effect muted">Nothing saved</span>;
  }
}

export function StepRow(p: Props) {
  const changed = p.was !== null && p.was.action !== p.d.action;
  return (
    <li className={`step ${p.selected ? "selected" : ""} ${changed ? "changed" : ""}`}>
      <div className="step-main" onClick={p.onSelect}>
        <span className="step-n" aria-hidden="true">{p.n}</span>
        <div className="msg">
          <span className="sr-only">Message {p.n}: </span>
          <span className="bubble">{p.message}</span>
        </div>
        <span className="gate" aria-hidden="true" />
        <div className="outcome">
          <div className="outcome-top">
            <Verdict d={p.d} />
            {changed && p.was && <span className="was-tag">was {verdict(p.was)}</span>}
            <ModeTag mode={p.d.mode} />
          </div>
          <Effect d={p.d} />
        </div>
      </div>
      <div className="step-why">
        <p>{whySentence(p.d)}</p>
        <button className="why-btn" aria-expanded={p.open} onClick={p.onToggle}>
          {p.open ? "Hide evidence" : "Why? Show evidence"}
        </button>
      </div>
      {p.caption && <p className="caption">{p.caption}</p>}
      {p.open && <Explanation d={p.d} thresholds={p.thresholds} summary={p.summary} onShowRule={p.onShowRule} />}
    </li>
  );
}
