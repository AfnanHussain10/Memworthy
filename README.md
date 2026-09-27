<h1 align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/AfnanHussain10/Memworthy/main/assets/logo-dark.png">
    <img alt="Memworthy" src="https://raw.githubusercontent.com/AfnanHussain10/Memworthy/main/assets/logo-light.png" width="380">
  </picture>
</h1>

<p align="center"><strong>Memory should be decided, not just extracted.</strong></p>

<p align="center">
  <img alt="Memworthy playground: a trip is ignored, a move updates memory, and a correction rolls it back" src="https://raw.githubusercontent.com/AfnanHussain10/Memworthy/main/assets/demo.gif" width="800">
</p>

Agent memory usually fails at the decision step, not at retrieval. Extraction pipelines are generous, so memory fills up with errors:
- temporary states stored as permanent facts ("in Dubai this week" becomes "lives in Dubai")
- plans stored as facts
- other people's facts stored as the user's
- stale values and ignored corrections
- the assistant's guesses saved as things the user said
- secrets
- no record of why anything was kept

Memworthy is a small Python library that sits between whatever proposes memories and whatever stores them. For each candidate it:
1. runs deterministic code checks
2. asks TypeSafe's Jev model one batch of typed questions
3. applies an ordered, user-editable policy to choose an action: `store`, `update`, `merge`, `supersede`, `reject`, `review`, `redact` or `store_labeled`

Every decision is written to a ledger you can audit, replay under a changed policy, and review.

## Quickstart

```bash
pip install "memworthy[jev]"              # Python 3.10+
export TYPESAFE_API_KEY=...             # https://typesafe.ai
```

```python
from memworthy import Candidate, DictStore, Gate

gate = Gate(policy="personal-memory", store=DictStore())
decisions = gate.ingest_messages([
    {"role": "user", "content": "I live in Dubai"},
    {"role": "user", "content": "Flying to Riyadh tomorrow"},
    {"role": "user", "content": "I moved to Riyadh last week"},
    {"role": "user", "content": "Actually I'm only considering it"},
])
for d in decisions:
    print(f"{d.action:10} {d.rule:16} {d.candidate.text}")
# store      rules[9]         I live in Dubai
# reject     not_memory       Flying to Riyadh tomorrow
# update     update_existing  I moved to Riyadh last week
# supersede  retracted        Actually I'm only considering it   (rolls back to Dubai)
```

The output above is what the bundled recorded Jev answers give; a live run may differ slightly. You can reproduce it with no API key:

```python
from memworthy import RecordedJudge
from memworthy.judges.recorded import bundled_fixture_path

gate = Gate("personal-memory", DictStore(),
            judge=RecordedJudge(bundled_fixture_path("personal-memory")))
```

Each decision also lands in `memworthy.ledger.jsonl` with every signal, its probability, the rule that fired, and the policy and model version.

### Other integrations

```python
# Wrap a Mem0 client: only approved content reaches Mem0 (pip install "memworthy[jev,mem0]")
from mem0 import Memory
from memworthy import GatedMemory
memory = GatedMemory(Memory(), policy="personal-memory")          # mode="input" or "candidate"
memory.add([{"role": "user", "content": "I'm in Lisbon this week"}], user_id="alice")  # rejected
```

```bash
# Turn Claude Code / Codex sessions into an Obsidian-compatible Markdown knowledge base
memworthy run dev-sessions ~/.claude/projects --store markdown:~/kb
memworthy run dev-sessions ~/.claude/projects --store markdown:~/kb --extractor llm   # OpenRouter via EXTRACTOR_MODEL
```

## CLI

| Command | What it does |
| --- | --- |
| `memworthy test POLICY [--judge recorded\|jev\|mock] [--pairs FILE]` | Runs the policy's tests; exits 1 on failure (CI-friendly with recorded answers) |
| `memworthy run POLICY SOURCE [--store dict\|markdown:PATH\|mem0] [--dry-run]` | Gates a candidate file, chat JSON or session folder |
| `memworthy replay LEDGER POLICY [--only-changed]` | Shows which past decisions a policy change would flip (no API calls when prompts are unchanged) |
| `memworthy lint POLICY [--strict]` | Overlapping types, unused signals, unreachable rules, vague prompts |
| `memworthy review LEDGER [--export-tests FILE]` | Accept, override or skip queued decisions; overrides become tests |
| `memworthy record POLICY INPUT` | Records live Jev answers as fixtures |
| `memworthy eval POLICY` | Contrast-pair metrics, calibration and plots into `eval/results/` |

## Templates

Both are ordinary YAML files in `src/memworthy/templates/`; copy one and edit it.

**`personal-memory`** (v1.1) is for consumer assistants.
- **Types:** fact, preference, relationship, temporary, intent, hypothetical, noise.
- **Rules, in order:**
  1. Redact secrets.
  2. Reject anything the user didn't say.
  3. Roll back retractions.
  4. Reject temporary states, plans, hypotheticals and noise.
  5. Reject future or time-bounded statements. Dates are parsed by code, not the judge.
  6. Review sensitive data (health, finances, religion, precise location).
  7. Reject low-durability facts.
  8. Review facts about someone else.
  9. Update memories the new fact replaces.
  10. Store the rest.

```yaml
rules:
  - {name: secrets, when: "secret", then: redact}
  - {name: not_user, when: "not from_user", then: reject}
  - {name: retracted, when: "retraction > 0.7 and conflict", then: supersede, restore: true}
  - {name: not_memory, when: "type in ['temporary', 'intent', 'hypothetical', 'noise']", then: reject}
  - {name: bounded_time, when: "timing == 'bounded' or timing == 'future'", then: reject}
  - {name: sensitive, when: "sensitivity >= 1.5", then: review}
  - {name: low_durability, when: "durable < 0.6 or explicit < 0.5", then: reject}
  - {name: wrong_subject, when: "about_subject < 0.5", then: review}
  - {name: update_existing, when: "conflict and conflict.p > 0.6", then: update}
  - {else: store}
```

**`dev-sessions`** (v1.1) turns coding-agent sessions into a knowledge base.
- **Pipeline:**
  1. Sessions are split into episodes.
  2. Each episode is classified with one Jev call, and noise is dropped.
  3. Candidates are extracted.
  4. Each candidate is gated.
- **Types:** task, fix, decision, discussion, explanation, concept, convention, noise.
- **What happens to each kind:**
  - Unverified fixes and tasks are labeled `unverified`, meaning no passing tests, build, commit or user sign-off.
  - Explanations not grounded in files read are labeled.
  - Unfinished discussions become open questions.
  - Proposals the user did not endorse go to review.
  - Abandoned approaches and generic textbook content are rejected.
  - Later decisions supersede earlier ones, and the old entry moves to `_archive/`.
  - Secrets are redacted before the judge sees them.

Policies use a small, safe expression language (a hand-written parser, never `eval`). For anything it can't express, register Python checks and rules with `@memworthy.check` and `@memworthy.rule`.

## Evaluation results

All numbers come from real `jev-1.13.0` answers, regenerated with `memworthy eval <policy>`. Full reports, including every failure, are in [`eval/results/`](https://github.com/AfnanHussain10/Memworthy/blob/main/eval/results/README.md).

Contrast pairs are held out: one changed word flips the correct action, labels come from the template, and the policies were frozen before the pairs were recorded.

| Template | Cases | Action accuracy | Pair consistency | Target |
| --- | --- | --- | --- | --- |
| `personal-memory` v1.1 | 272 | 97.4% | 94.4% | ≥90% / ≥85%: met |
| `dev-sessions` v1.1 | 236 | 91.5% | 83.9% | pair consistency misses 85% |

- **First run.** Three pair templates had labeling or wording errors and were corrected after the first run. That run scored 94.5% / 88.1% and 87.3% / 75.4%; it is kept in the repo, and the corrections are listed in `eval/results/README.md`.
- **Remaining failures (genuine):**
  - A question that embeds a fact ("Since I live in Vienna, what…") is read as an intent.
  - Failed fixes are rejected as noise instead of being labeled unverified.
  - Some project-specific facts are typed as explanations and labeled ungrounded.
- **Latency and cost.** The median Jev round trip was about 1 s from the author's machine, which misses the 500 ms target. The median cost is about $0.00003 per candidate.
- **Calibration.** Raw ECE is 0.05–0.29 on small samples. See the reports for what the temperature-scaled numbers do and do not mean.
- **Built-in tests are not evidence.** The template tests (124 and 105) pass 100%, but they were used to tune the prompts.
- **LongMemEval knowledge-update, with vs without Memworthy: pending real run.** Run it with `python eval/longmemeval.py longmemeval_s_cleaned.json --limit 78`; details are in `eval/results/longmemeval/README.md`.

## Playground

`playground/` has a FastAPI backend that imports this library and a React front end:
- a guided Dubai → Riyadh demo, one timeline row per message: message → verdict → effect on memory, with "Why?" showing the rule, judge answers and thresholds
- free play with example messages
- a policy panel with one-click experiments, rule switches and a YAML editor; edits replay the conversation and mark changed decisions
- the recorded coding-session demo
- the evaluation page

```bash
pip install -e ".[dev,jev]"
uvicorn playground.backend.app:app --port 8765     # open http://localhost:8765
```

The built front end is committed in `playground/web/`. To change it, edit `playground/ui/` and rebuild:

```bash
cd playground/ui && npm ci
npm run dev        # http://localhost:5173, proxies /api to the backend on :8765
npm run build      # typechecks, then writes ../web
```

Replay mode uses the bundled recorded answers and needs no key. Live mode needs `TYPESAFE_API_KEY`. It is rate-limited per IP (40 calls per hour) and globally (600 per hour), and has a daily spend cap (`PLAYGROUND_DAILY_CAP_USD`, default $0.50). Every decision is labeled recorded, live or needs-live.

## Development

```bash
pyenv install -s 3.12 && python -m venv .venv
.venv/bin/pip install -e ".[dev,jev,mem0]"
.venv/bin/pytest -q && .venv/bin/mypy src && .venv/bin/ruff check .
```

Tests never call live APIs; `pytest -m live` runs a few real Jev calls when `TYPESAFE_API_KEY` is set. Design decisions are in `docs/decisions.md` and build status is in `PROGRESS.md`.

## License

Apache 2.0.
