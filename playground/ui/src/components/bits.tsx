// Small shared pieces: verdict pill, judge-mode tag, empty state.
import type { Decision, JudgeMode } from "../api";
import { ACTION_HELP, MODE, TONE, verdict } from "../labels";

export function Verdict({ d, size = "md" }: { d: Pick<Decision, "action" | "patch">; size?: "sm" | "md" }) {
  return (
    <span className={`verdict tone-${TONE[d.action]} ${size}`} title={`${d.action}: ${ACTION_HELP[d.action]}`}>
      {verdict(d)}
    </span>
  );
}

export function ModeTag({ mode }: { mode: JudgeMode }) {
  return <span className={`mode-tag m-${mode}`} title={MODE[mode].help}>{MODE[mode].label}</span>;
}

export function Empty({ children }: { children: React.ReactNode }) {
  return <p className="empty">{children}</p>;
}
