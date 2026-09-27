// Plain-language words for library terms. The technical name is always shown next to them.
import type { Action, Decision, JudgeMode, Signal, Thresholds } from "./api";

export type Tone = "store" | "update" | "reject" | "review" | "redact";

export const TONE: Record<Action, Tone> = {
  store: "store", store_labeled: "store", update: "update", merge: "update",
  supersede: "update", reject: "reject", review: "review", redact: "redact",
};

/** The verdict a visitor reads, e.g. "Ignored" for reject. */
export function verdict(d: Pick<Decision, "action" | "patch">): string {
  switch (d.action) {
    case "store": return "Saved";
    case "store_labeled": return "Saved, labeled";
    case "update": return "Updated";
    case "merge": return "Merged";
    case "supersede": return d.patch?.restore ? "Rolled back" : "Replaced";
    case "reject": return "Ignored";
    case "review": return "Needs review";
    case "redact": return "Redacted";
  }
}

export const ACTION_HELP: Record<Action, string> = {
  store: "Saved as a new memory.",
  store_labeled: "Saved as a new memory with a warning label.",
  update: "Changes an existing memory.",
  merge: "Combined with an existing memory.",
  supersede: "Retires an existing memory and puts another in its place.",
  reject: "Not worth remembering, so nothing is saved.",
  review: "Held back for a person to check before it is saved.",
  redact: "Contains a secret; the secret is removed before anything is saved.",
};

export const MODE: Record<JudgeMode, { label: string; help: string }> = {
  recorded: { label: "recorded", help: "Judge answers were recorded from real Jev calls, so replay is free and instant." },
  live: { label: "live", help: "Judged just now by a live Jev call." },
  "needs-live": { label: "needs live call", help: "This input is not in the recorded demo; it needs a live judge call." },
  rules: { label: "rules only", help: "Decided by code checks alone; no judge call was needed." },
};

/** "rules[9]" is the unnamed else rule at the end of the policy. */
export function ruleName(rule: string): string {
  if (rule === "on_error") return "on_error";
  return /^rules\[\d+\]$/.test(rule) ? "default" : rule;
}

/** One sentence on why the decision happened. */
export function whySentence(d: Decision): string {
  if (d.mode === "needs-live") return "This message is not in the recorded demo, so it needs a live judge call.";
  if (d.rule === "on_error") return `The judge was unavailable, so the policy's fallback applies.`;
  if (ruleName(d.rule) === "default") return `No rule objected, so the default applies (${d.reason.split(" · ").slice(0, 2).join(" · ")}).`;
  return `Rule ${d.rule} matched: ${d.reason}.`;
}

export interface SignalView {
  name: string;
  shown: string;
  frac: number;
  marks: number[];
  kind: Signal["kind"];
  /** true when the value is above the highest threshold drawn on the bar */
  over: boolean | null;
}

/** A signal as a 0..1 bar with its rule thresholds, for the explanation panel. */
export function signalView(s: Signal, thresholds: Thresholds, levels: number): SignalView {
  const t = thresholds[s.name] ?? [];
  if (s.kind === "noul") {
    const v = Number(s.value);
    return { name: s.name, shown: `${Math.round(v * 100)}%`, frac: v, marks: t, kind: s.kind,
      over: t.length ? v > t[0] : null };
  }
  if (s.kind === "score") {
    const max = Math.max(1, levels - 1);
    const v = Number(s.value);
    return { name: s.name, shown: v.toFixed(2), frac: v / max, marks: t.map((x) => x / max),
      kind: s.kind, over: t.length ? v >= t[0] : null };
  }
  const p = (s.probabilities ?? {})[String(s.value)] ?? 0;
  const pm = thresholds[`${s.name}.p`] ?? [];
  return { name: `${s.name} = ${String(s.value)}`, shown: `${Math.round(p * 100)}%`, frac: p,
    marks: pm, kind: s.kind, over: pm.length ? p > pm[0] : null };
}

export const pct = (x: number | null | undefined, digits = 0): string =>
  x == null ? "n/a" : `${(x * 100).toFixed(digits)}%`;
