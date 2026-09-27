// The "why" panel for one decision: rule that fired, every signal against its threshold.
import type { Decision, PolicySummary, Thresholds } from "../api";
import { ACTION_HELP, MODE, ruleName, signalView } from "../labels";

interface Props {
  d: Decision;
  thresholds: Thresholds;
  summary: PolicySummary;
  onShowRule?: (ruleId: string) => void;
}

export function Explanation({ d, thresholds, summary, onShowRule }: Props) {
  const rule = summary.rules.find((r) => r.id === d.rule);
  const checks = d.signals.filter((s) => s.kind === "check");
  const typeSig = d.signals.find((s) => s.name === "type");
  const conflict = d.signals.find((s) => s.name === "conflict");
  const judged = d.signals.filter((s) => s.kind !== "check" && s.name !== "type" && s.name !== "conflict");
  const levels = (name: string) => Object.keys(d.signals.find((s) => s.name === name)?.probabilities ?? {}).length;
  const typeP = typeSig?.probabilities?.[d.type];

  return (
    <div className="explain">
      <section>
        <h4>Decision</h4>
        <p><code>{d.action}</code> · {ACTION_HELP[d.action]}</p>
      </section>

      <section>
        <h4>Rule that decided it</h4>
        <div className="rule-fired">
          <span className="rule-name">{ruleName(d.rule)}</span>
          <code>{rule?.when ? `when ${rule.when}` : d.rule_line}</code>
          <span className="arrow">→ {d.action}</span>
          {onShowRule && rule && (
            <button className="link" onClick={() => onShowRule(rule.id)}>show in policy</button>
          )}
        </div>
        <p className="hint">Rules are checked top to bottom; the first one that matches decides.</p>
      </section>

      {typeSig && (
        <section>
          <h4>Type</h4>
          <p>
            <code>{d.type}</code> {typeP != null && <span className="muted">({Math.round(typeP * 100)}% sure)</span>}
            {summary.type_help[d.type] && <span className="muted"> · {summary.type_help[d.type]}</span>}
          </p>
        </section>
      )}

      {conflict && conflict.value !== "none" && d.target && (
        <section>
          <h4>Existing memory it touches</h4>
          <p>“{d.target}” <span className="muted">({Math.round((conflict.probabilities?.[String(conflict.value)] ?? 0) * 100)}% sure)</span></p>
        </section>
      )}

      {judged.length > 0 && (
        <section>
          <h4>What the judge answered</h4>
          <ul className="signals">
            {judged.map((s) => {
              const v = signalView(s, thresholds, levels(s.name));
              return (
                <li key={s.name}>
                  <div className="sig-head">
                    <code>{v.name}</code>
                    <span className="sig-val">{v.shown}</span>
                  </div>
                  <div className="bar" role="img"
                    aria-label={`${v.name} ${v.shown}${v.marks.length ? `, threshold ${v.marks.join(", ")}` : ""}`}>
                    <i className={v.over === null ? "" : v.over ? "over" : "under"} style={{ width: `${Math.max(2, v.frac * 100)}%` }} />
                    {v.marks.map((m) => <b key={m} style={{ left: `${Math.min(100, m * 100)}%` }} title={`rule threshold ${m}`} />)}
                  </div>
                  {summary.signals[s.name] && <p className="question">{summary.signals[s.name]}</p>}
                </li>
              );
            })}
          </ul>
          <p className="hint">The dark tick on a bar is a threshold used by a rule.</p>
        </section>
      )}

      {checks.length > 0 && (
        <section>
          <h4>Code checks (no model involved)</h4>
          <div className="chips">
            {checks.map((s) => (
              <span key={s.name} className={`chip ${s.value === true ? "yes" : s.value === false ? "no" : ""}`}
                title={summary.signals[s.name]}>
                {s.name}: {String(s.value)}
              </span>
            ))}
          </div>
        </section>
      )}

      {d.error && <p className="error-note">Judge error: {d.error}</p>}
      <p className="meta">
        judge {MODE[d.mode].label} · model {d.model ?? "none"} · policy {d.policy} v{d.policy_version}
        {d.latency_ms ? ` · ${d.latency_ms} ms` : ""}
      </p>
    </div>
  );
}
