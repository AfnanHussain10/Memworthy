// dev-sessions demo: recorded coding sessions become a Markdown knowledge base.
import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError, track, type Answers, type Config, type Decision, type SessionResult } from "../api";
import { ACTION_HELP, verdict, whySentence } from "../labels";
import { Explanation } from "../components/Explanation";
import { Ledger } from "../components/Ledger";
import { PolicyPanel } from "../components/PolicyPanel";
import { Effect } from "../components/StepRow";
import { ModeTag, Verdict } from "../components/bits";

const T = "dev-sessions" as const;
const GOOD = new Set(["tests_passed", "build_passed", "committed", "user_confirmed"]);

export function SessionsDemo({ cfg, dark }: { cfg: Config; dark: boolean }) {
  const base = cfg.templates[T];
  const [data, setData] = useState<SessionResult | null>(null);
  const [prev, setPrev] = useState<Map<string, Decision> | null>(null);
  const [open, setOpen] = useState<Set<string>>(new Set());
  const [policyOpen, setPolicyOpen] = useState(false);
  const [yaml, setYaml] = useState(base.yaml);
  const [applied, setApplied] = useState<string | null>(null);
  const [focusRule, setFocusRule] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [error, setError] = useState("");
  const answers = useRef<Answers>({});

  const load = useCallback(async (policy: string | null) => {
    const r = await api.sessions({ policy_yaml: policy, live: false, answers: answers.current });
    Object.assign(answers.current, r.new_answers);
    setData(r);
    return r;
  }, []);

  useEffect(() => {
    load(null).then(() => track("session_demo")).catch((e) => setError(e instanceof ApiError ? e.readable : "Could not load the demo."));
  }, [load]);

  async function apply(y: string | null): Promise<string | null> {
    try {
      const before = new Map((data?.decisions ?? []).map((d) => [d.text, d]));
      await load(y);
      setApplied(y);
      setPrev(y ? prev ?? before : null);
      track("rule_edit");
      return null;
    } catch (e) {
      return e instanceof ApiError ? e.readable : "Could not apply the policy.";
    }
  }

  const toggle = (id: string) => setOpen((o) => { const n = new Set(o); if (n.has(id)) n.delete(id); else n.add(id); return n; });
  const counts = new Map<string, number>();
  for (const d of data?.decisions ?? []) counts.set(verdict(d), (counts.get(verdict(d)) ?? 0) + 1);
  const dropped = data?.episodes.filter((e) => e.dropped).length ?? 0;
  const changed = prev && data ? data.decisions.filter((d) => prev.get(d.text) && prev.get(d.text)!.action !== d.action).length : null;
  const sel = data?.decisions.find((d) => d.id === selected) ?? null;

  return (
    <div className={`demo ${policyOpen ? "with-policy" : ""}`}>
      <section className="intro">
        <h1>Turn coding sessions into a knowledge base.</h1>
        <p>
          Memworthy reads recorded Claude Code and Codex sessions, splits them into episodes, drops the noise, and decides which
          lessons are worth keeping. Unverified work is saved with a label, and secrets are removed before a judge sees them.
        </p>
        {data && (
          <ol className="funnel" aria-label="Pipeline">
            <li><strong>{data.episodes.length}</strong> episodes</li>
            <li><strong>{dropped}</strong> dropped as noise</li>
            <li><strong>{data.decisions.length}</strong> candidate memories</li>
            <li className="verdicts">{[...counts].map(([v, n]) => <span key={v}><strong>{n}</strong> {v.toLowerCase()}</span>)}</li>
          </ol>
        )}
      </section>

      <div className="workspace">
        <section className="timeline" aria-labelledby="h-eps">
          <header className="panel-head">
            <h2 id="h-eps">Episodes from 6 recorded sessions</h2>
            <button className="ghost small" onClick={() => setPolicyOpen(!policyOpen)} aria-expanded={policyOpen}>{policyOpen ? "Hide policy" : "Edit policy"}</button>
          </header>
          {error && <p className="error-note pad">{error}</p>}
          {!data && !error && <p className="muted pad">Replaying the sessions…</p>}
          <ol className="episodes">
            {data?.episodes.map((e, i) => {
              const decs = data.decisions.filter((d) => d.episode_id === e.id);
              return (
                <li key={e.id} className={`episode ${e.dropped ? "dropped" : ""}`}>
                  <div className="ep-head">
                    <span className="step-n">{i + 1}</span>
                    <div>
                      <p className="ep-req">“{e.request}”</p>
                      <div className="chips">
                        <span className="chip">{e.type ?? "unclassified"}</span>
                        <span className={`chip ${GOOD.has(e.outcome) ? "yes" : "no"}`} title="How the episode ended">{e.outcome.replace("_", " ")}</span>
                        {e.files_edited.length > 0 && <span className="chip">{e.files_edited.length} file{e.files_edited.length > 1 ? "s" : ""} edited</span>}
                        {e.dropped && <span className="chip">noise {Math.round(e.noise * 100)}%: dropped before any memory is judged</span>}
                      </div>
                    </div>
                  </div>
                  {decs.length > 0 && (
                    <ul className="ep-decisions">
                      {decs.map((d) => {
                        const was = prev?.get(d.text) ?? null;
                        const ch = was !== null && was.action !== d.action;
                        return (
                          <li key={d.id} className={`${ch ? "changed" : ""} ${selected === d.id ? "selected" : ""}`}>
                            <div className="outcome-top" onClick={() => setSelected(d.id)}>
                              <Verdict d={d} />
                              {ch && was && <span className="was-tag">was {verdict(was)}</span>}
                              <ModeTag mode={d.mode} />
                            </div>
                            <Effect d={d} />
                            <div className="step-why">
                              <p>{whySentence(d)}</p>
                              <button className="why-btn" aria-expanded={open.has(d.id)} onClick={() => { toggle(d.id); setSelected(d.id); }}>
                                {open.has(d.id) ? "Hide evidence" : "Why? Show evidence"}
                              </button>
                            </div>
                            {open.has(d.id) && <Explanation d={d} thresholds={data.thresholds} summary={base}
                              onShowRule={(id) => { setPolicyOpen(true); setFocusRule(id); }} />}
                          </li>
                        );
                      })}
                    </ul>
                  )}
                </li>
              );
            })}
          </ol>
          {data && <Ledger jsonl={data.ledger} />}
        </section>

        <section className="side" aria-labelledby="h-kb">
          <header className="panel-head"><h2 id="h-kb">Knowledge base</h2></header>
          <div className="memory">
            <p className="panel-sub">{data?.files.length ?? 0} Markdown files written by <code>--store markdown:~/kb</code>. Open one to see the file.</p>
            {data?.files.map((f) => (
              <details key={f.path} className="mdfile">
                <summary>
                  <span className="mono muted">{f.path}</span>
                  <span className="mem-text">{f.memory.text.slice(0, 90)}{f.memory.text.length > 90 ? "…" : ""}
                    {f.memory.labels.map((l) => <span key={l} className="label">{l}</span>)}</span>
                </summary>
                <pre>{f.markdown}</pre>
              </details>
            ))}
            <p className="hint">{ACTION_HELP.redact} Look for <code>[REDACTED:openai]</code> in the entries.</p>
          </div>
        </section>

        {policyOpen && (
          <PolicyPanel template={T} base={base} yaml={yaml} setYaml={setYaml} apply={apply} applied={applied}
            firedRule={sel?.rule ?? null} focusRule={focusRule} changed={changed} dark={dark}
            onClose={() => { setPolicyOpen(false); setFocusRule(null); }} />
        )}
      </div>
    </div>
  );
}
