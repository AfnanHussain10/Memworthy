// Policy side panel: one-click experiments, a readable rule list with switches, and the raw YAML.
import { lazy, Suspense, useEffect, useRef, useState } from "react";
import { api, type TemplateInfo, type TemplateName, type TestResult, type Validation } from "../api";
import { disableRule, enableRule, EXPERIMENTS } from "../experiments";
import { Verdict } from "./bits";

const YamlEditor = lazy(() => import("./YamlEditor"));

interface Props {
  template: TemplateName;
  base: TemplateInfo;
  yaml: string;
  setYaml: (y: string) => void;
  /** Replays the demo under this YAML (null = the unedited template). */
  apply: (yaml: string | null) => Promise<string | null>;
  applied: string | null;
  firedRule: string | null;
  focusRule: string | null;
  changed: number | null;
  onClose: () => void;
  dark: boolean;
}

type Tab = "rules" | "yaml";

export function PolicyPanel(p: Props) {
  const [tab, setTab] = useState<Tab>("rules");
  const [valid, setValid] = useState<Validation | null>(null);
  const [status, setStatus] = useState<string>("");
  const [tests, setTests] = useState<TestResult | "running" | null>(null);
  const [busy, setBusy] = useState(false);
  const timer = useRef<number | undefined>(undefined);
  const lines = p.base.yaml.split("\n");
  const dirty = p.yaml !== (p.applied ?? p.base.yaml);

  useEffect(() => {
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => {
      api.validate(p.template, p.yaml).then(setValid).catch(() => undefined);
    }, 350);
    return () => window.clearTimeout(timer.current);
  }, [p.yaml, p.template]);

  useEffect(() => {
    if (p.focusRule) setTab("rules");
  }, [p.focusRule]);

  async function run(yaml: string, what: string) {
    setBusy(true);
    p.setYaml(yaml);
    const err = await p.apply(yaml === p.base.yaml ? null : yaml);
    setBusy(false);
    setStatus(err ?? what);
    setTests(null);
  }

  async function runTests() {
    setTests("running");
    try { setTests(await api.test(p.template, p.yaml)); } catch { setTests(null); setStatus("Fix the YAML error first."); }
  }

  const edits = diffCount(p.base.yaml, p.yaml);

  return (
    <aside className="policy" aria-label="Policy editor">
      <header className="policy-head">
        <div>
          <h2>Policy <span className="muted mono">{p.template} v{p.base.version}</span></h2>
          <p className="panel-sub">An ordered list of rules. Each message goes down the list and the first rule that matches decides.</p>
        </div>
        <button className="icon" onClick={p.onClose} aria-label="Close policy">✕</button>
      </header>

      <section className="experiments" aria-label="Experiments">
        <h3>Try an experiment</h3>
        {EXPERIMENTS[p.template].map((e) => (
          <button key={e.id} className={`exp ${p.applied !== null && p.applied === e.edit(p.base.yaml) ? "on" : ""}`} disabled={busy}
            aria-pressed={p.applied !== null && p.applied === e.edit(p.base.yaml)} onClick={() => run(e.edit(p.base.yaml), `Applied “${e.title}”. Changed rows are marked in the timeline.`)}>
            <strong>{e.title}</strong>
            <span>{e.expect}</span>
          </button>
        ))}
      </section>

      <div className="tabs" role="tablist">
        <button role="tab" aria-selected={tab === "rules"} onClick={() => setTab("rules")}>Rules</button>
        <button role="tab" aria-selected={tab === "yaml"} onClick={() => setTab("yaml")}>YAML {edits > 0 && <span className="count">{edits} line{edits === 1 ? "" : "s"} changed</span>}</button>
      </div>

      {tab === "rules" ? (
        <ol className="rules">
          {p.base.rules.map((r, i) => {
            const line = r.line ? lines[r.line - 1] : "";
            const single = /^\s*- \{.*\}\s*$/.test(line);
            const on = p.yaml.includes(line);
            const off = single && p.yaml.includes(line.replace(/^(\s*)- /, "$1# - "));
            const cls = [r.id === p.firedRule && "fired", r.id === p.focusRule && "focus", !on && "off"].filter(Boolean).join(" ");
            return (
              <li key={r.id} className={cls}>
                <span className="rule-n">{i + 1}</span>
                <div className="rule-body">
                  <div className="rule-top">
                    <strong className="mono">{r.name ?? "default"}</strong>
                    <span className="then">→ <Verdict d={{ action: r.then, patch: r.restore ? { restore: true, old_text: "", new_text: "", target_id: "" } : null }} size="sm" /></span>
                  </div>
                  <code className="when">{r.when ? `when ${r.when}` : "everything else"}</code>
                  {r.id === p.firedRule && <span className="fired-note">decided the selected message</span>}
                  {!on && !off && <span className="fired-note">edited in YAML</span>}
                </div>
                {single && (on || off) && (
                  <label className="switch" title={on ? "Turn this rule off" : "Turn this rule on"}>
                    <input type="checkbox" checked={on} disabled={busy}
                      onChange={() => run(on ? disableRule(p.yaml, line) : enableRule(p.yaml, line),
                        `Rule ${r.name} turned ${on ? "off" : "on"}; the conversation was replayed.`)} />
                    <span aria-hidden="true" />
                    <span className="sr-only">{r.name} enabled</span>
                  </label>
                )}
              </li>
            );
          })}
        </ol>
      ) : (
        <div className="yaml-wrap">
          <Suspense fallback={<p className="muted">Loading editor…</p>}>
            <YamlEditor value={p.yaml} onChange={p.setYaml} dark={p.dark}
              errorLine={valid && !valid.ok ? valid.line : null} />
          </Suspense>
        </div>
      )}

      <footer className="policy-foot">
        <p className={`status ${valid && !valid.ok ? "err" : ""}`} aria-live="polite">
          {valid && !valid.ok ? `Line ${valid.line ?? "?"}: ${valid.error}` : status || (dirty ? "Edited. Press Apply to replay the conversation." : "Valid policy.")}
          {p.changed != null && p.applied && !(valid && !valid.ok) && <> <strong>{p.changed} decision{p.changed === 1 ? "" : "s"} changed.</strong></>}
        </p>
        <div className="row">
          <button className="primary" disabled={!dirty || busy || (valid !== null && !valid.ok)} onClick={() => run(p.yaml, "Applied: the conversation was replayed under your policy.")}>Apply</button>
          <button disabled={busy || (p.yaml === p.base.yaml && !p.applied)} onClick={() => run(p.base.yaml, "Reset to the template.")}>Reset</button>
          <button className="ghost" onClick={runTests}>Run built-in tests</button>
        </div>
        {tests === "running" && <p className="muted">Running the policy's examples on recorded answers…</p>}
        {tests && tests !== "running" && (
          <p className="muted">
            {tests.passed}/{tests.total} examples pass{tests.needs_live ? `; ${tests.needs_live} need live calls` : ""}.
            {tests.failures[0] && <> First failure: “{tests.failures[0].input}” ({tests.failures[0].reason}).</>}
          </p>
        )}
      </footer>
    </aside>
  );
}

function diffCount(a: string, b: string): number {
  if (a === b) return 0;
  const A = a.split("\n");
  const B = b.split("\n");
  const sa = new Set(A);
  const sb = new Set(B);
  return B.filter((l) => !sa.has(l)).length + A.filter((l) => !sb.has(l)).length;
}
