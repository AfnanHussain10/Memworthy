# Memworthy decision log

Where the tech spec, PRD and playground design are silent, Memworthy takes the simplest option and records it here. Items marked **(spec updated)** changed the tech spec first because they touch a public model or interface.

## Project setup

- **Doc filenames.** The goal names the docs `docs/memworthy-tech-spec.md` and similar; the repo has `docs/Memworthy v0.1 technical spec.md`, `docs/Memworthy v0.1 PRD.md` and `docs/Memworthy playground design.md`. They are the same documents and keep their names.
- **Private docs stay untracked.** The initial `.gitignore` ignored `/docs`. The three planning docs stay local (untracked), and only `docs/decisions.md` is committed. Spec edits are therefore local; each one is also summarized here.
- **Python and tooling.** pyenv 3.12.13 (`.python-version`), `python -m venv .venv`, `pip install -e ".[dev,jev,mem0]"`. `requires-python` stays `>=3.10` as the spec says; code avoids 3.11-only APIs.
- **`jev` extra is empty.** `httpx` is already a core dependency (spec), so `memworthy[jev]` needs nothing more. The extra still exists so `pip install "memworthy[jev]"` works and documents intent.
- **PyPI name.** `memgate` is taken on PyPI (0.4.2, another project in the same field: "Privacy-aware memory isolation for AI agents"), and it installs a top-level `memgate` module too. The project was renamed to Memworthy; see "Rename to Memworthy" below.
- **License.** Apache 2.0 (the existing `LICENSE`).

## Jev and judges

- **System One contract verified** against docs.typesafe.ai on 2026-09-25 and with one live call: base `https://api.typesafe.ai/v1`, `POST /systemone`, Bearer auth, question/answer shapes as in the spec. Real score probabilities are keyed by level index (`"0"`, `"1"`...); `JevJudge` maps them to level names. **(spec updated)**
- **Limits.** The official docs give token limits (64k per request) rather than a question count. Memworthy caps model signals at 60 per policy and types at 255 (Jev's choice limit); user choice signals stay at 2–20 options.
- **Single-type policies** skip the `type` question because Jev choices need two or more options; the decision's type is the only type. **(spec updated)**
- **Engine validates every judge's answers** (missing answer or unknown option), not only `JevJudge`, so custom judges get the same error handling.
- **Any exception from a judge** (not only `JudgeError`) becomes an `on_error` decision, so a buggy judge never crashes the pipeline.
- **Recorded fixtures**: one JSON file per policy keyed by sha256 of (state, questions, model); each entry keeps the raw Jev response for contract tests. Bundled template fixtures live in `memworthy/templates/fixtures/`. **(spec updated)**

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
- **`memworthy record INPUT`** accepts `tests`, `pairs`, a pair `.yaml`, a `.chat.json` script (messages gated in order with state carried between them) or a candidates `.json`/`.jsonl`; `--fresh` drops stale entries when prompts change.
- **`memworthy test --judge mock`** uses an unconfigured `MockJudge` (defaults only), so it exercises plumbing, not policy quality; CI uses `--judge recorded`.

## Sessions and dev-sessions (milestone 3)

- **Session fixtures: real format, invented content.** The parsers were built against the author's real Claude Code (2.1.251-2.1.281) and Codex (0.107-0.130) sessions, scrubbed and reviewed. Real sessions still carry internal work even when scrubbed (a first scrubbed batch even contained CV and passport details that no regex caught), so on the author's instruction none are committed. `scripts/make_session_fixtures.py` rebuilds the exact record layouts with an invented "bookshelf" project. `scripts/scrub_sessions.py` remains for users who want to test their own sessions locally.
- **Parser behavior.** Claude Code: `user`/`assistant` records, `tool_use`/`tool_result` blocks joined by id, `is_error` for failures; `isMeta`, sidechain and harness text (`<command-…>`, `<local-command…>`, `<system-reminder>`) skipped; everything else skipped with a debug log. Codex: `session_meta` for id, version and cwd; `response_item` messages, `function_call`/`custom_tool_call` joined to outputs by `call_id`; exit codes read from `Process exited with code N`, `Exit code: N` or JSON `metadata.exit_code`; injected user messages (`<environment_context>`, `# AGENTS.md`, `<skill>`, …) skipped; `event_msg` duplicates ignored.
- **Episode facts.** `files_read` also counts read-only shell commands (`cat`, `sed -n`, `head`, `tail`, `nl -ba`). Outcome priority: a successful `git commit` > last test command > last build command > a short affirmative final user reply > `unknown`; a failing last test or build is `failed`. Episodes with neither a user turn nor a tool call are dropped.
- **Episode subject** is the session's working-directory name (new `Episode.project`), so conflicts are only compared within one project. **(spec updated)**
- **Default candidate (no extractor):** the first user message as source text and the last assistant message with at least 12 words (else the final one) as the candidate, because final messages are often one-liners like "Committed as abc123". `referenced_files` are the file paths named in that text, else the episode's edited files.
- **Episode classification failure keeps the episode** (fail open to gating, where `on_error` applies).
- **LLM extractor** (`memworthy.extractors`): a minimal `OpenAICompatibleClient` over httpx (no new dependency) or any client with `chat.completions.create`; `openrouter_extractor_from_env()` uses `OPENROUTER_API_KEY` and `EXTRACTOR_MODEL`. A malformed reply falls back to the default candidate. Acceptance runs use no extractor so recorded answers stay deterministic.
- **Markdown store**: files are named from the first 8 words of the text, with a 6-character id suffix on collision; YAML anchors are disabled so frontmatter reads cleanly in Obsidian; an update keeps its file (and `previous_text`); superseding writes the old entry to `_archive/` and removes it from the live folder.
- **`PolicyTest.source_text`** lets tests mirror session candidates (entry text differs from the user's request), and **`PolicyTest.expect` may be a list** of acceptable actions for genuinely ambiguous cases. The list form is used only for proposals the user defers ("maybe later"), which fairly read either as an unendorsed decision (review) or an open question (store_labeled). **(spec updated)**
- **dev-sessions tuning, reported honestly.** Starting from the spec's template (v1.0) on the first 102 tests: **72/102** with real Jev answers. Changes to v1.1 (**105/105** on 105 tests):
  - The spec's `concept` description ("not specific to this codebase") contradicted its own rule that keeps project-specific concepts; it now reads "a technical insight or lesson … general or project-specific". `explanation` is "how a specific module, file or data flow works". `decision` covers choices "made or proposed"; `noise` names routine setup and checks.
  - New `routine` signal (reject above 0.7) for housekeeping that `worth_keeping` let through (`npm install`, retries).
  - `unverified_fix` became `unverified_work` and also labels tasks that are not verified (the PRD labels unfinished tasks).
  - `endorsed` asks whether the user "stated this themselves or clearly approved it (not just heard it suggested)" (stated conventions went to review otherwise).
  - Conflict prompt "Which existing knowledge-base entry is no longer accurate once the candidate memory is true?" (real supersedes ≥0.85, unrelated entries ≤0.01 in the lab; the default prompt gave about 0.4).
  - Test changes, each for a stated reason: type assertions dropped where types genuinely overlap and the action is the contract (a performance fix typed task or fix; concluded discussions typed decision; noise typed task; supersedes); hedging words removed from two ungrounded-explanation tests (they confounded grounding with usefulness); one "concept" test that was really a gotcha replaced; three unrelated-existing-entry tests added as negatives for supersede.
- **Built-in tests are tuning data, not evaluation** (same as personal-memory); held-out numbers come from contrast pairs (milestone 5).
- **The CLI layer is `cli.py` plus `cli_support.py`**; both may print.

## Mem0 adapter and CLI (milestone 4)

- **Mem0 verified (mem0ai 2.2.0, pinned `>=2.2,<2.3`)**: `add(messages, *, user_id|agent_id|run_id, metadata, infer=False)` stores each non-system message verbatim; `search(query, filters=..., top_k=...)` (not `limit=`); `update(memory_id, text=..., metadata=...)` merges metadata into the payload; `get`, `get_all(filters=...)`, `delete`. **(spec updated)**
- **Mem0Store** is bound to one Mem0 scope (user, agent or run id). Memworthy fields go into Mem0 metadata with a `memworthy_` prefix (`type`, `subject`, `labels`, `decision_id`, `policy`, `policy_version`, `previous_text`, `merged`). `similar()` searches with the candidate text plus context, like the local stores. `update` and `supersede` call Mem0's `update` on the target; a supersede with no patch (retraction of something with no previous version) deletes the target, since Mem0 has no archive; `merge` records the decision id in `memworthy_merged`. Sync and async Mem0 clients both work (sync calls run in a thread).
- **GatedMemory input mode** gates every user and assistant message (assistant messages face the same policy, so `source_is_user` removes them), replaces redacted messages with their redacted text, drops `reject` and `review`, keeps system messages (Mem0 ignores them), and calls Mem0's own `add` with the caller's arguments. If nothing is left, Mem0 is not called. The result is Mem0's dict plus `memworthy_decisions`; `last_decisions` holds the Decision objects.
- **GatedMemory candidate mode** uses the Gate's extractor (or one candidate per user message) and writes approved candidates itself with `infer=False`.
- **Contract tests run offline**: `Memory.from_config` with an in-memory `QdrantClient(":memory:")`, a local hashing embedder injected after construction, and the LLM replaced by a function that fails the test if called. They are marked `contract` and still run in the default suite because they need no network.
- **Replay** compares the new policy's `questions_hash` (types, model-signal prompts/options/levels and the conflict prompt; `applies_to` excluded because masking is re-applied) with each decision's. Equal: rules re-run over the recorded values, and recorded check values are reused by name (the ledger holds redacted candidates, so re-running `secret_scan` would wrongly say "no secret"). Different: with `--fixtures`, re-judge through a RecordedJudge using the decision's target as the only conflict option; otherwise the decision is listed as needing live calls. Short-circuited decisions are replayed when the new policy still short-circuits them; errored ones always need a live call. **(spec updated)**
- **Replay changes** are counted when the action or the label set differs.
- **Lint checks**: more than 12 types; overlapping type descriptions (content-word Jaccard ≥ 0.5); signals no rule uses (skipped when `py:` rules exist); duplicate conditions (unreachable); constant `true`/`false` conditions; probability comparisons that can never hold (`> 1`, `< 0`); vague prompts (fewer than 4 words, not a question, or words like "good", "relevant", "important"); conflict enabled with no rule that uses it. Both templates lint clean under `--strict`.
- **Review queue**: decisions whose action is `review` or that carry an error. Resolutions go to a sidecar `<ledger>.reviews.jsonl` so the ledger stays append-only. Accept records the decision's action as correct; override records the chosen action and exports a policy test (`--export-tests`, appended to a YAML list); skip leaves it queued. Overrides are not applied to the store (review = ledger queue only).

## Evaluation (milestone 5)

- **Held-out discipline.** Both policies were frozen at v1.1 before the contrast pairs were recorded, and the pairs were never used to change prompts, thresholds or rules.
- **Pair-file corrections, disclosed.** After run 1, three pair templates were corrected because their labels or wording were wrong (grammar in "{who} {fact}" plus a health fact that is sensitive by design; a temporary "training for a marathon" labeled review; proposals worded "Decided to use"). Run 1 is kept in `eval/results/*/run1-uncorrected-pairs/`, and both runs are reported.
- **Pair grouping.** Cases sharing a fill combination form one pair; list-style templates group cases with an explicit `pair:` key. Pair consistency counts only groups with two or more cases.
- **Calibration** is measured per signal only for categories where that signal decides the case (`calibrate: {signal, positive}` in the pair file). The label is whether the expected action is in `positive`. Temperature scaling is fitted and scored with 2-fold cross-validation over pair groups. The report states that temperatures far below 1 turn probabilities into near-hard decisions, so a near-zero scaled ECE means separation at 0.5, not fine calibration.
- **Latency and cost** come from the recorded live calls in the fixture files (median round trip, and median input tokens × $0.042 per million; output tokens are free). The ~1 s median misses the PRD's 500 ms target; it includes the network round trip from the author's machine.
- **LongMemEval** (MIT, `longmemeval_s_cleaned.json`, 78 knowledge-update questions): runner implemented with a shared LLM extraction for both arms, cached and resumable. It is **pending a real run** because the configured free `EXTRACTOR_MODEL` was rate-limited upstream (HTTP 429) and the key is on OpenRouter's free tier (about 50 free-model requests per day). The author chose to leave it pending. Grading uses one LLM call per question with the baseline always shown as answer "a"; position bias is a known limitation to revisit when it runs.
- **`memworthy eval`** writes `metrics.json`, `summary.md` and PNG plots to `eval/results/<policy>/`; matplotlib is only in the dev extra, and mypy skips following matplotlib/numpy (numpy's stubs use syntax that mypy rejects for a 3.10 target).

## Playground (milestone 6)

- **FastAPI backend (recommended by the design doc) rather than Pyodide.** It is stateless: the browser sends the conversation and policy on each request, and the server re-runs them with the real library and discards the input. Only anonymous event counts are kept in memory.
- **Judge answers**, in order:
  1. Bundled recorded fixtures, labeled "recorded".
  2. Live answers the browser received earlier and sends back, labeled "live". The server keeps no content cache.
  3. A new live Jev call if live mode is enabled and within limits.
  4. Otherwise the decision falls to `on_error` and is labeled "needs live call".
- **Rule edits replay the whole conversation** through the Gate with the same judge. When the questions are unchanged, the recorded answers still match, so edits work instantly in replay mode, as the design doc asks.
- **Limits:**
  - 300 characters per message, 12 messages, 100 KB of policy YAML (raised from 20 KB in the UI redesign: the `dev-sessions` template is 47 KB, so every Apply on it failed).
  - Live calls: 40 per IP per hour, 600 per hour globally.
  - Daily spend cap `PLAYGROUND_DAILY_CAP_USD` (default $0.50), computed from reported input tokens × $0.042 per million.
  - When a limit is hit, live mode shows a friendly message and replay keeps working.
- **Front end (superseded):** the first version was plain HTML, CSS and ES modules with no build step. See "Playground UI redesign" below.
- **Session demo** uses all six fixture sessions copied to `playground/data/sessions/`, so conflict shortlists and recorded answers match the recorded run.
- **Suggested rule edits:**
  - `personal-memory`: delete the `retracted` rule, and step 4 no longer rolls back.
  - `dev-sessions`: make `unverified_work` reject, and the unverified upload fix leaves the knowledge base.
- **Hosting and the domain** are left to the author (open question in the design doc).

## Playground UI redesign

- **Why.** The three-column layout was hard to read: no line said what Memworthy is, messages ran top-down while decisions ran bottom-up, action names (`supersede`, `rules[9]`) were jargon, the ledger repeated the decisions, and the policy drawer was a YAML wall that covered its own results.
- **Research.** Cedar playground (a sentence of context and example pickers first; policy in its own tab), Rego playground (policy, input and output visible together, with a numbered "try it out" script), regex101 (an explanation panel that annotates the pattern), Letta ADE (memory as persistent labeled blocks), and dev-tool demo practice (guided tour first, then a sandbox with specific calls to action).
- **Layout: timeline + inspector** (chosen by the author over polishing the three columns or a Rego-style editor split). Each message is one row: message → plain verdict ("Saved", "Ignored", "Rolled back") → effect on memory. The library action name stays visible in the evidence and in tooltips. "Why?" expands the explanation: the rule that fired, every judge answer as a bar with the rule's threshold and the signal's question, and the code checks. Memory for the selected message is pinned on the right. A three-step stepper (Watch, Try, Change a rule) replaces the Guided/Free play switch.
- **Policy panel** opens beside the timeline, not over it. It has one-click experiments (each checked against recorded answers so it visibly changes a decision), a Rules tab where single-line rules have on/off switches (off = the YAML line is commented out, so it can be switched back on) and replay immediately, and the raw YAML tab (CodeMirror 6, lazy-loaded). Changed rows show "was <old verdict>".
- **React + TypeScript with Vite**, source in `playground/ui/`, built into `playground/web/`. **The build output is committed**, so the backend still runs from a Python-only checkout or host. Rebuild with `npm ci && npm run build` in `playground/ui/`. `index.html` is served with `Cache-Control: no-cache` because it names the hashed asset files.
- **Backend additions for the UI** (playground only, no library API change): `/api/config` and `/api/validate` return each policy's rules (id, when, then, line), signal questions and type descriptions.

## Rename to Memworthy

- **Why.** `memgate` on PyPI belongs to another AI-agent memory project and installs a `memgate` module, so keeping the import name and changing only the distribution name would let the two packages overwrite each other, and `pip install memgate` would fetch the wrong product.
- **Choice.** `memworthy` ("is this memory-worthy?") was free on PyPI, had no GitHub account and no GitHub repositories. Other names checked: `winnow`, `sift`, `keepsake`, `engram`, `lethe`, `hippo`, `curate`, `memkeeper`, `recallgate` and `memguard` are taken on PyPI; `memsift`, `memsense`, `memvet` and `memscreen` are free but close to existing memory projects on GitHub.
- **Scope.** Everything changed together, since nothing had been released: distribution, import package (`src/memworthy`), CLI (`memworthy`), env var `MEMWORTHY_MODEL`, ledger header `{"memworthy_ledger": 1}` and file `memworthy.ledger.jsonl`, fixture header `memworthy_fixtures`, Mem0 metadata prefix `memworthy_` and the `memworthy_decisions` result key. **(spec updated)**
- **Recorded answers stay valid**: fixture keys hash the state, questions and model, never the package name.
- **GitHub and local folder** were renamed too: the repository is now `AfnanHussain10/Memworthy` (GitHub redirects the old URL) and the checkout is `~/Memworthy`.
- **Published** `memworthy` 0.1.0 to PyPI on 2026-09-27 (wheel and sdist; sdist includes are anchored so it holds only the package, README, LICENSE and pyproject).

