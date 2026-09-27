# Evaluation results

All numbers come from real `jev-1.13.0` answers recorded with `memworthy record` (fixtures in `src/memworthy/templates/fixtures/`, `synthetic: false`) and are regenerated with `memworthy eval <policy>`. Policies were frozen at v1.1 before the contrast pairs were recorded; the pairs were not used for tuning.

## Contrast pairs (held out)

| Template | Cases | Pairs | Action accuracy | Pair consistency | Target | Median Jev latency | Median cost / candidate |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `personal-memory` v1.1 | 272 | 125 | 97.4% | 94.4% | ≥90% / ≥85% | 999 ms | $0.000027 |
| `dev-sessions` v1.1 | 236 | 118 | 91.5% | 83.9% | ≥90% / ≥85% | 1012 ms | $0.000028 |

Latency is the median Jev round trip measured while recording (network included); cost is the median input tokens per call times $0.042 per million (output tokens are free).

**Run 1 (before pair-file corrections), kept for the record** in `*/run1-uncorrected-pairs/`:

- `personal-memory`: 274 cases, accuracy 94.5%, pair consistency 88.1%.
- `dev-sessions`: 236 cases, accuracy 87.3%, pair consistency 75.4%.

Three pair templates were corrected after run 1 because the labels or wording, not the model, were wrong: `personal-memory`'s "{who} {fact}" produced "I works ..." and mixed a health fact (sensitive, so review by design) into a third-party pair; its "training for a marathon" pair expected review for a temporary state that the policy rejects first; `dev-sessions`' proposal side said "Decided to use ...", contradicting its own context. Prompts, thresholds and rules were not changed. The remaining failures are listed in each `summary.md` and are genuine: questions that embed a fact ("Since I live in Vienna, what ...") read as intents, owning a house reads as sensitive, failed fixes are rejected as noise instead of labeled unverified, some unendorsed proposals are rejected as noise, and project-specific facts are typed as explanations and labeled ungrounded.

Built-in template tests (124 and 105) pass 100%, but they were used for tuning (106/120 and 72/102 before), so they are not evidence of accuracy.

## Calibration

See the Calibration section of each `summary.md` and the `calibration_*.png` plots. Raw ECE ranges from 0.05 to 0.29 on small samples; the fitted temperatures are well below 1, so the raw probabilities are under-confident but mostly on the correct side of 0.5.

## LongMemEval knowledge-update comparison

**Pending real run** (see `longmemeval/README.md` for the command and why).
