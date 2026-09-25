# MemGate v0.1 progress

Acceptance commands are run from a clean copy of the tracked files with `scripts/clean_check.sh` (fresh pyenv 3.12 venv, `pip install -e ".[dev,jev,mem0]"`, no `.env`).

## Milestone 1: core engine

- [x] Pydantic models (`models.py`), frozen, JSON-serializable
- [x] Policy schema, YAML loader with line-numbered errors, JSON Schema export
- [x] Safe expression language (hand-written recursive-descent parser, closures, no `eval`)
- [x] Engine: checks, pre-judge short-circuit, conflict shortlist, one judge call, masking, rules, apply, ledger
- [x] `JevJudge` (System One contract verified against docs.typesafe.ai), `MockJudge`, `RecordedJudge` and `RecordingJudge`
- [x] `DictStore` with BM25 `similar()`; `JsonlLedger` and `MemoryLedger`
- [x] Built-in code checks registered (`source_is_user`, `secret_scan`, `date_parse`, `file_was_read`, `outcome_verified`)
- [x] `Gate` with async and sync APIs, subject-ordered concurrency

**Acceptance (clean copy):**

| Check | Result |
| --- | --- |
| `pytest tests/unit -q` | 193 passed |
| `mypy src` (strict) | Success: no issues found in 28 source files |
| `ruff check` | All checks passed |
| Policy with a syntax error reports the correct line | `test_yaml_syntax_error_exact_line`, `test_errors_report_line` (25 cases) |
| Expression parser rejects `__import__('os')` | `test_rejects_unsafe_or_invalid`, `test_import_is_rejected_at_parse_time` |
| Coverage on `policy/`, `engine.py`, `checks/` (target 90%) | 98% |

## Milestone 2: checks and `personal-memory`

- [ ] Template with at least 100 built-in tests
- [ ] Recorded fixtures from real Jev calls
- [ ] `memgate test`, `memgate record`
- [ ] Contrast-pair generator

## Milestone 3: sessions and `dev-sessions`

- [ ] Claude Code and Codex parsers (from real scrubbed samples)
- [ ] Episode splitting, classification, extractor hook, Markdown sink

## Milestone 4: Mem0 adapter and CLI

- [ ] `GatedMemory`, `Mem0Store`; `run`, `replay`, `lint`, `review`

## Milestone 5: evaluation

- [ ] Contrast-pair metrics, calibration, plots in `eval/results/`

## Milestone 6: playground and launch

- [ ] Playground (FastAPI plus front end), README, wheel install check
