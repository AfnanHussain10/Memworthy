// personal-memory demo: guided replay, free play and rule edits on one timeline.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, ApiError, track, type Answers, type Config, type Decision, type RunResult } from "../api";
import { MemoryPanel } from "../components/MemoryPanel";
import { PolicyPanel } from "../components/PolicyPanel";
import { StepRow } from "../components/StepRow";
import { Ledger } from "../components/Ledger";

const T = "personal-memory" as const;
const CAPTIONS = [
  "A lasting fact, stated by the user about themselves, so it is saved.",
  "Travel is temporary. It is ignored instead of becoming where the user lives.",
  "A past move contradicts what is stored, so Dubai is updated to Riyadh.",
  "The user walks it back, so the update is rolled back and Dubai returns.",
];
const PRESETS = [
  "If I were a doctor, I'd work in pediatrics",
  "My sister is a pilot",
  "My API key is sk-proj-Ab12Cd34Ef56Gh78Ij90Kl12",
  "I'm in Lisbon this week",
  "I've been vegetarian for ten years",
];
const STEP_MS = 3500;

type Phase = "watch" | "try" | "rule";

export function ChatDemo({ cfg, dark }: { cfg: Config; dark: boolean }) {
  const base = cfg.templates[T];
  const [messages, setMessages] = useState(cfg.demo.map((m) => m.content));
  const [run, setRun] = useState<RunResult | null>(null);
  const [prev, setPrev] = useState<Decision[] | null>(null);
  const [visible, setVisible] = useState(1);
  const [playing, setPlaying] = useState(true);
  const [phase, setPhase] = useState<Phase>("watch");
  const [selected, setSelected] = useState<number | null>(null);
  const [open, setOpen] = useState<Set<number>>(new Set());
  const [policyOpen, setPolicyOpen] = useState(false);
  const [yaml, setYaml] = useState(base.yaml);
  const [applied, setApplied] = useState<string | null>(null);
  const [focusRule, setFocusRule] = useState<string | null>(null);
  const [live, setLive] = useState(false);
  const [draft, setDraft] = useState("");
  const [note, setNote] = useState("");
  const answers = useRef<Answers>({});
  const listRef = useRef<HTMLOListElement>(null);

  const replay = useCallback(async (msgs: string[], policy: string | null): Promise<RunResult> => {
    const r = await api.run({ template: T, policy_yaml: policy, live, answers: answers.current,
      messages: msgs.map((content) => ({ role: "user", content })) });
    Object.assign(answers.current, r.new_answers);
    setNote(r.blocked ?? "");
    setRun(r);
    return r;
  }, [live]);

  const started = useRef(false);
  useEffect(() => {
    if (started.current) return;
    started.current = true;
    replay(messages, null).catch(() => undefined);
  }, [replay, messages]);

  // Guided autoplay: reveal one message at a time.
  useEffect(() => {
    if (!playing || phase !== "watch" || !run) return;
    if (visible >= messages.length) { setPlaying(false); track("guided_step4"); return; }
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const id = window.setTimeout(() => setVisible((v) => v + 1), reduce ? STEP_MS + 1000 : STEP_MS);
    return () => window.clearTimeout(id);
  }, [playing, visible, phase, run, messages.length]);

  const steps = run?.steps.slice(0, visible) ?? [];
  const sel = selected ?? steps.length - 1;
  const current = steps[sel];
  const before = useMemo(() => (sel > 0 ? new Set(steps[sel - 1].memories.map((m) => `${m.id}|${m.text}`)) : new Set<string>()),
    [steps, sel]);
  const changed = prev && run ? run.steps.filter((s, i) => prev[i] && prev[i].action !== s.decision.action).length : null;
  const guidedCaptions = phase === "watch" && !applied && messages.length === cfg.demo.length;
  const done = visible >= messages.length;

  function goPhase(p: Phase) {
    setPhase(p);
    if (p === "watch") { setVisible(1); setSelected(null); setPlaying(true); }
    if (p === "try") { setPlaying(false); setVisible(messages.length); setSelected(null); track("free_play"); }
    if (p === "rule") { setPlaying(false); setVisible(messages.length); setPolicyOpen(true); }
  }

  async function applyPolicy(y: string | null): Promise<string | null> {
    try {
      const before = run?.steps.map((s) => s.decision) ?? null;
      await replay(messages, y);
      setApplied(y);
      setPrev(y ? before && (prev ?? before) : null);
      setVisible(messages.length);
      setSelected(null);
      setPlaying(false);
      track("rule_edit");
      return null;
    } catch (e) {
      return e instanceof ApiError ? e.readable : "Could not apply the policy.";
    }
  }

  async function send(text: string) {
    const t = text.trim();
    if (!t) return;
    const msgs = [...messages, t].slice(-cfg.limits.messages);
    setMessages(msgs); setDraft(""); setPrev(null);
    try {
      await replay(msgs, applied);
      setVisible(msgs.length); setSelected(null);
      setOpen(new Set([msgs.length - 1]));
      requestAnimationFrame(() => listRef.current?.lastElementChild?.scrollIntoView({ block: "nearest", behavior: "smooth" }));
    } catch (e) {
      setNote(e instanceof ApiError ? e.readable : "Request failed.");
    }
  }

  function toggle(i: number) {
    setOpen((o) => { const n = new Set(o); if (n.has(i)) n.delete(i); else n.add(i); return n; });
    setSelected(i);
  }

  function retiredBy(memId: string) {
    const i = steps.findIndex((s) => s.archive.some((a) => a.id === memId));
    if (i >= 0) { setSelected(i); setOpen((o) => new Set(o).add(i)); }
  }

  return (
    <div className={`demo ${policyOpen ? "with-policy" : ""}`}>
      <section className="intro">
        <h1>Memworthy decides what an AI should remember.</h1>
        <p>
          Every message goes through a <strong>policy</strong>: rules you can read and edit, plus a judge model's answers
          to a few questions (is this lasting? is it about the user?). Each decision comes with its reason.
        </p>
        <ol className="stepper">
          {([["watch", "Watch the demo"], ["try", "Try your own message"], ["rule", "Change a rule"]] as const).map(([id, label], i) => (
            <li key={id}>
              <button className={phase === id ? "on" : ""} aria-current={phase === id ? "step" : undefined} onClick={() => goPhase(id)}>
                <span className="dot">{i + 1}</span>{label}
              </button>
            </li>
          ))}
        </ol>
      </section>

      <div className="workspace">
        <section className="timeline" aria-labelledby="h-timeline">
          <header className="panel-head">
            <h2 id="h-timeline">Conversation</h2>
            {phase === "watch" && (
              <div className="player" aria-label="Demo controls">
                <span className="muted">message {Math.min(visible, messages.length)} of {messages.length}</span>
                <button className="icon" aria-label="Previous message" disabled={visible <= 1} onClick={() => { setPlaying(false); setVisible((v) => Math.max(1, v - 1)); setSelected(null); }}>◀</button>
                <button className="icon" aria-label={playing ? "Pause" : "Play"} onClick={() => { if (done) setVisible(1); setPlaying(!playing); setSelected(null); }}>{playing ? "❚❚" : "▶"}</button>
                <button className="icon" aria-label="Next message" disabled={done} onClick={() => { setPlaying(false); setVisible((v) => v + 1); setSelected(null); }}>▶▶</button>
              </div>
            )}
            {phase !== "watch" && <button className="ghost small" onClick={() => setPolicyOpen(!policyOpen)} aria-expanded={policyOpen}>{policyOpen ? "Hide policy" : "Edit policy"}</button>}
          </header>
          <div className="legend" aria-hidden="true"><span>Message</span><span>Decision and effect on memory</span></div>

          {!run && <p className="muted pad">Loading the demo…</p>}
          <ol className="steps" ref={listRef}>
            {steps.map((s, i) => (
              <StepRow key={`${i}-${s.decision.id}`} n={i + 1} message={messages[i]} d={s.decision}
                was={prev && prev[i] ? prev[i] : null}
                caption={guidedCaptions && i === visible - 1 ? CAPTIONS[i] : null}
                selected={i === sel && steps.length > 1} open={open.has(i)}
                onSelect={() => setSelected(i)} onToggle={() => toggle(i)}
                thresholds={run!.thresholds} summary={base}
                onShowRule={(id) => { setPolicyOpen(true); setFocusRule(id); }} />
            ))}
          </ol>

          {phase === "watch" && done && run && (
            <div className="next-card">
              <p><strong>That's the idea.</strong> A trip was ignored, a move updated memory, and a correction rolled it back. Now try it yourself.</p>
              <div className="row">
                <button className="primary" onClick={() => goPhase("try")}>Try your own message</button>
                <button onClick={() => goPhase("rule")}>Change a rule</button>
              </div>
            </div>
          )}

          {phase !== "watch" && (
            <form className="composer" onSubmit={(e) => { e.preventDefault(); send(draft); }}>
              <div className="chips" aria-label="Example messages">
                <span className="muted">Try:</span>
                {PRESETS.map((p) => <button type="button" key={p} className="chip-btn" onClick={() => send(p)}>{p}</button>)}
              </div>
              <div className="compose-row">
                <label className="sr-only" htmlFor="msg">Message</label>
                <input id="msg" value={draft} onChange={(e) => setDraft(e.target.value)} maxLength={cfg.limits.message_chars}
                  placeholder="Tell the assistant something about yourself…" autoComplete="off" />
                <button className="primary" type="submit" disabled={!draft.trim()}>Send</button>
              </div>
              <div className="compose-meta">
                <label title={cfg.live_available ? "Judge new messages with a live Jev call" : "Live mode is off on this server"}>
                  <input type="checkbox" checked={live} disabled={!cfg.live_available} onChange={(e) => setLive(e.target.checked)} /> Live judge
                </label>
                <span className="muted">
                  {note || (cfg.live_available ? "Messages not in the recorded demo need live mode." : "This server replays recorded answers only; new messages are marked “needs live call”.")}
                </span>
                <button type="button" className="link" onClick={() => { setMessages([]); setRun(null); setVisible(0); setPrev(null); replay([], applied).catch(() => undefined); }}>Clear</button>
              </div>
            </form>
          )}
          {run && <Ledger jsonl={run.ledger} />}
        </section>

        <section className="side" aria-labelledby="h-mem">
          <header className="panel-head"><h2 id="h-mem">Memory</h2></header>
          <MemoryPanel title={steps.length ? `What the AI remembers after message ${sel + 1}` : "What the AI remembers"}
            memories={current?.memories ?? []} archive={current?.archive ?? []} before={sel >= 0 ? before : null}
            restored={current?.decision.patch?.restore ? current.decision.patch.new_text : null}
            onRetiredClick={(m) => retiredBy(m.id)} />
        </section>

        {policyOpen && (
          <PolicyPanel template={T} base={base} yaml={yaml} setYaml={setYaml} apply={applyPolicy} applied={applied}
            firedRule={current?.decision.rule ?? null} focusRule={focusRule} changed={changed} dark={dark}
            onClose={() => { setPolicyOpen(false); setFocusRule(null); }} />
        )}
      </div>
    </div>
  );
}
