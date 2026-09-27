// Evaluation numbers, read from /api/eval (eval/results/*/metrics.json); never typed by hand.
import { useEffect, useState } from "react";
import { api, track } from "../api";
import { pct } from "../labels";

interface Metrics {
  policy_version: string;
  model: string;
  cases: number;
  pairs: number;
  accuracy: number;
  pair_consistency: number;
  judge_errors: number;
  categories: Record<string, { n: number; accuracy: number; pair_consistency: number }>;
  calibration: Record<string, { n: number; ece_before: number; ece_after_cv: number; temperature_all: number }>;
  calls?: { latency_ms_median?: number; cost_usd_per_candidate_median?: number };
  failures: { input: string; category: string; expected: string | string[]; got: string; rule: string }[];
  plots: string[];
}

const TEMPLATES = [
  ["personal-memory", "Chat assistant memory"],
  ["dev-sessions", "Coding-session knowledge base"],
] as const;

export function Evaluation() {
  const [data, setData] = useState<Record<string, unknown> | null>(null);
  useEffect(() => { api.evalResults().then(setData); track("eval_page"); }, []);
  if (!data) return <div className="page"><p className="muted">Loading…</p></div>;
  const lme = (data.longmemeval ?? {}) as { complete?: boolean; baseline_accuracy?: number; memworthy_accuracy?: number; questions_done?: number };

  return (
    <div className="page">
      <h1>Evaluation</h1>
      <p className="lead">
        How often does Memworthy make the right call? Each test is a <strong>contrast pair</strong>: two messages that differ
        by one detail, where that detail flips the correct action. “I moved to Riyadh” should update memory; “I might move to
        Riyadh” should not. Labels come from the template, not from a model. Pairs are held out from policy tuning.
      </p>

      {TEMPLATES.map(([name, title]) => {
        const r = data[name] as Metrics | undefined;
        if (!r) return <section key={name}><h2>{title}</h2><p className="notice">Pending real run.</p></section>;
        const cats = Object.entries(r.categories).sort((a, b) => a[1].accuracy - b[1].accuracy);
        return (
          <section key={name} className="eval-block">
            <h2>{title} <span className="muted mono">{name} v{r.policy_version} · {r.model}</span></h2>
            <div className="tiles">
              <Tile label="Right action" value={pct(r.accuracy, 1)} note={`target 90% · ${r.cases} cases`} ok={r.accuracy >= 0.9} />
              <Tile label="Both halves of a pair right" value={pct(r.pair_consistency, 1)} note={`target 85% · ${r.pairs} pairs`} ok={r.pair_consistency >= 0.85} />
              <Tile label="Median judge latency" value={r.calls?.latency_ms_median != null ? `${Math.round(r.calls.latency_ms_median)} ms` : "n/a"} note="at recording time" />
              <Tile label="Median cost per message" value={r.calls?.cost_usd_per_candidate_median != null ? `$${r.calls.cost_usd_per_candidate_median.toFixed(6)}` : "n/a"} note={`${r.judge_errors} judge errors`} />
            </div>

            <h3>Accuracy by category <span className="muted">(hardest first; the line marks the 90% target)</span></h3>
            <ul className="hbars">
              {cats.map(([c, v]) => (
                <li key={c} title={`${c}: ${pct(v.accuracy, 1)} of ${v.n} cases, pair consistency ${pct(v.pair_consistency, 1)}`}>
                  <span className="mono">{c.replaceAll("_", " ")}</span>
                  <span className="hbar"><i style={{ width: `${v.accuracy * 100}%` }} /><b style={{ left: "90%" }} /></span>
                  <span className="num">{pct(v.accuracy)} <span className="muted">n={v.n}</span></span>
                </li>
              ))}
            </ul>

            <details>
              <summary>Calibration of the judge's probabilities</summary>
              <table>
                <thead><tr><th>Signal</th><th>n</th><th>ECE raw</th><th>ECE scaled (2-fold CV)</th><th>Temperature</th></tr></thead>
                <tbody>{Object.entries(r.calibration).map(([s, v]) => (
                  <tr key={s}><td className="mono">{s}</td><td>{v.n}</td><td>{v.ece_before.toFixed(3)}</td><td>{v.ece_after_cv.toFixed(3)}</td><td>{v.temperature_all.toFixed(2)}</td></tr>
                ))}</tbody>
              </table>
              <p className="hint">Temperatures well below 1 push probabilities to 0 or 1, so a near-zero scaled ECE means the signal separates these cases at 0.5, not fine calibration. Samples are small.</p>
              <div className="plots">{r.plots.map((p) => <img key={p} loading="lazy" alt={`${p} for ${name}`} src={`/results/${name}/${p}`} />)}</div>
            </details>

            <details>
              <summary>Known failures ({r.failures.length})</summary>
              <ul className="failures">
                {r.failures.map((f, i) => (
                  <li key={i}>“{f.input}” <span className="muted">· {f.category.replaceAll("_", " ")} · expected <code>{[f.expected].flat().join("/")}</code>, got <code>{f.got}</code> by rule <code>{f.rule}</code></span></li>
                ))}
              </ul>
            </details>
          </section>
        );
      })}

      <section className="eval-block">
        <h2>LongMemEval knowledge-update, with and without Memworthy</h2>
        {lme.complete ? (
          <p>Baseline {pct(lme.baseline_accuracy, 1)}, with Memworthy {pct(lme.memworthy_accuracy, 1)} on {lme.questions_done} questions.</p>
        ) : (
          <p className="notice">Pending real run{lme.questions_done ? ` (${lme.questions_done} of 78 questions done)` : ""}. Command: <code>python eval/longmemeval.py longmemeval_s_cleaned.json --limit 78</code></p>
        )}
      </section>
    </div>
  );
}

function Tile({ label, value, note, ok }: { label: string; value: string; note: string; ok?: boolean }) {
  return (
    <div className="tile">
      <span className="tile-label">{label}</span>
      <span className="tile-value">{value}</span>
      <span className="tile-note">{ok !== undefined && <span className={ok ? "ok" : "miss"}>{ok ? "✓ meets" : "✗ below"}</span>} {note}</span>
    </div>
  );
}
