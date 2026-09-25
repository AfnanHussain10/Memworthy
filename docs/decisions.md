# MemGate decision log

Where the tech spec, PRD and playground design are silent, MemGate takes the simplest option and records it here. Items marked **(spec updated)** changed the tech spec first because they touch a public model or interface.

## Project setup

- **Doc filenames.** The goal names the docs `docs/memgate-tech-spec.md` and similar; the repo has `docs/MemGate v0.1 technical spec.md`, `docs/MemGate v0.1 PRD.md` and `docs/MemGate playground design.md`. They are the same documents and keep their names.
- **Private docs stay untracked.** The initial `.gitignore` ignored `/docs`. The three planning docs stay local (untracked), and only `docs/decisions.md` is committed. Spec edits are therefore local; each one is also summarized here.
- **Python and tooling.** pyenv 3.12.13 (`.python-version`), `python -m venv .venv`, `pip install -e ".[dev,jev,mem0]"`. `requires-python` stays `>=3.10` as the spec says; code avoids 3.11-only APIs.
- **`jev` extra is empty.** `httpx` is already a core dependency (spec), so `memgate[jev]` needs nothing more. The extra still exists so `pip install "memgate[jev]"` works and documents intent.
- **PyPI name.** `memgate` is taken on PyPI (0.4.2, another project). The distribution keeps the name `memgate` for local wheels; a public release needs a new name (open item for the author).
- **License.** Apache 2.0 (the existing `LICENSE`).

## Jev and judges

- **System One contract verified** against docs.typesafe.ai on 2026-09-25 and with one live call: base `https://api.typesafe.ai/v1`, `POST /systemone`, Bearer auth, question/answer shapes as in the spec. Real score probabilities are keyed by level index (`"0"`, `"1"`...); `JevJudge` maps them to level names. **(spec updated)**
- **Limits.** The official docs give token limits (64k per request) rather than a question count. MemGate caps model signals at 60 per policy and types at 255 (Jev's choice limit); user choice signals stay at 2–20 options.
- **Single-type policies** skip the `type` question because Jev choices need two or more options; the decision's type is the only type. **(spec updated)**
- **Engine validates every judge's answers** (missing answer or unknown option), not only `JevJudge`, so custom judges get the same error handling.
- **Any exception from a judge** (not only `JudgeError`) becomes an `on_error` decision, so a buggy judge never crashes the pipeline.
- **Recorded fixtures**: one JSON file per policy keyed by sha256 of (state, questions, model); each entry keeps the raw Jev response for contract tests. Bundled template fixtures live in `memgate/templates/fixtures/`. **(spec updated)**

## Policy format and expressions

- **`when:`** is the rule key (PRD example fixed). `if:` gives a clear load error pointing at `when:`.
- **Extra reserved names**: `meta`, `true`, `false`, `and`, `or`, `not`, `in` cannot be signal names, since they would shadow expression syntax. **(spec updated)**
- **Literal checks at load time.** `type == 'x'`, `type in [...]`, choice-signal comparisons and `candidate.role` comparisons must use declared names; typos fail at load with the line number. **(spec updated)**
- **`on_error`** is limited to `review`, `reject` or `store`; actions that need a target or a label make no sense without judge answers.
- **Truthiness of strings.** A bare string value (for example a `date_parse` result) is truthy unless it is empty or `none`. Numbers are truthy above 0.5 (the spec's Noul rule), lists when non-empty.
- **Expression hardening**: identifiers cannot start with `_`, function-call syntax is rejected, and expressions are capped at 2,000 characters and 50 levels of nesting.
- **Two `else` rules**: the error points at the misplaced (non-final) one.

## Engine and stores

- **Retraction restore.** New `Rule.restore` (supersede only) and `Patch.restore`. `update` keeps the replaced text in `metadata.previous_text`; a restoring supersede archives the target and re-creates the previous text as a new memory with the target's type. With no previous text it archives only. `personal-memory`'s `retracted` rule uses `restore: true`. **(spec updated)**
- **Decision fields.** `Decision.signals` also carries `type` and `conflict` (both nullable), plus new `labels` and `warnings` lists. **(spec updated)**
- **Short-circuited and errored decisions** have `type: "unknown"`.
- **Action without a target.** If a rule picks `update`, `merge` or `supersede` but the judge picked no conflicting memory, the engine stores instead and adds a warning.
- **Redaction wins.** Whenever `redacted_text` is set, stores write it (never the original), the decision gets the `redacted` label, and the ledger holds only the redacted candidate.
- **Conflict shortlist query** is the candidate text plus its context, within the same subject, so a short follow-up ("Actually I'm only considering it") still finds the memory it refers to. The candidate's type is unknown before judging, so the ranking does not filter by type. **(spec updated)**
- **State template** omits `Original message` when it equals the candidate text, and includes only a fixed set of metadata keys (episode type, outcome, files, commands, dependency versions); `timestamp` is never sent, so recorded fixtures stay stable.
- **Chat context** is the previous three messages as `role: content` lines.
- **`file_was_read`** returns false when the candidate references no files: there is nothing to ground it in.
- **`Candidate.from_text`** convenience constructor, and sync `ingest_messages`/`ingest_sessions` wrappers on `Gate` (the PRD quickstart calls `gate.ingest_sessions`). **(spec updated)**

## personal-memory template and fixtures (milestone 2)

- **Tuning history, reported honestly.** The spec's starting template (v1.0) scored **106/120** on its own built-in tests with real Jev answers. Changes that took it to v1.1 (**124/124**, with four added negative-conflict tests):
  - `date_parse` bug fix: "for six years" in a present-perfect sentence ("I've been a designer for six years") is a span up to now (`present`), not `bounded`.
  - State template: earlier messages first as their own block, candidate labeled `New message` (measured: context after the candidate dropped `durable` for "I moved to Riyadh last week" from 0.68 to 0.28). **(spec updated)**
  - `fact` and `relationship` descriptions no longer overlap ("family" moved to relationship).
  - Prompts chosen with `eval/prompt_lab.py` by comparing variants across groups of tests: `durable` ("lasting fact, preference or relationship rather than a short-lived state or passing plan"), `about_subject` (mentions preferences and relationships), `retraction` ("walk back ... rather than report a new change"), and a conflict prompt that asks for the memory "about the same thing" and says to pick `none` when the message only adds.
  - Thresholds: `about_subject < 0.5` (third-party max 0.17 vs own-life min 0.56 in the lab), `conflict.p > 0.6` (unrelated max 0.46 vs updates min 0.63).
  - `sensitive` moved ahead of `low_durability`, so sensitive facts go to review (consent) even when the judge doubts their durability.
  - A first attempt that reworded every prompt at once ("the candidate memory ...") dropped the score to 86/120; it was reverted. Wording sensitivity is real, as the PRD's risk table predicts.
- **Built-in tests are tuning data, not evaluation.** Because the prompts were tuned against these tests, the 124/124 pass rate is not a quality claim. The contrast pairs in `templates/pairs/personal-memory.yaml` use different wording and serve as the held-out set (milestone 5).
- **Conflict shortlist padding.** BM25 missed paraphrased conflicts ("I changed jobs, I'm a teacher now" vs "I work at a bank as an analyst"). `similar()` in local stores now returns BM25 matches first, then pads to `k` with the subject's most recently updated memories. **(spec updated)**
- **Bundled demo script** `templates/demos/personal-memory.chat.json` (the four Dubai/Riyadh messages) is recorded into the same fixture file; the replay gives store, reject (temporary 0.99), update, and a rollback to Dubai.
- **`memgate record INPUT`** accepts `tests`, `pairs`, a pair `.yaml`, a `.chat.json` script (messages gated in order with state carried between them) or a candidates `.json`/`.jsonl`; `--fresh` drops stale entries when prompts change.
- **`memgate test --judge mock`** uses an unconfigured `MockJudge` (defaults only), so it exercises plumbing, not policy quality; CI uses `--judge recorded`.
