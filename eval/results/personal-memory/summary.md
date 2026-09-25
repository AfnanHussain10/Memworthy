# personal-memory v1.1: contrast-pair evaluation

Judge `recorded`, model `jev-1.13.0`, 272 cases in 125 pairs (`personal-memory.yaml`), generated 2026-09-25.

| Metric | Value |
| --- | --- |
| Action accuracy | 97.4% |
| Pair consistency | 94.4% |
| Judge errors | 0 |
| Median Jev call latency (at recording) | 999 ms (p90 1117 ms) |
| Median input tokens / cost per candidate | 645 / $0.000027 |

## By category

| Category | Cases | Accuracy | Pair consistency |
| --- | --- | --- | --- |
| future_vs_past | 30 | 100.0% | 100.0% |
| hypothetical_vs_fact | 26 | 76.9% | 53.8% |
| intent_vs_fact | 36 | 100.0% | 100.0% |
| noise | 7 | 100.0% | n/a |
| preference | 14 | 100.0% | 100.0% |
| retraction | 9 | 100.0% | n/a |
| sensitive | 18 | 100.0% | 100.0% |
| source_role | 22 | 100.0% | 100.0% |
| temporary_vs_durable | 50 | 98.0% | 96.0% |
| update_vs_new | 24 | 100.0% | 100.0% |
| user_vs_third_party | 36 | 100.0% | 100.0% |

## Calibration

| Signal | n | ECE raw | ECE temperature-scaled (2-fold CV) | T (all data) |
| --- | --- | --- | --- | --- |
| about_subject | 36 | 0.120 | 0.000 | 0.06 |
| durable | 50 | 0.117 | 0.000 | 0.11 |
| retraction | 9 | 0.057 | 0.000 | 0.27 |

Labels are the template's expected action for categories where the named signal decides the case. A fitted temperature well below 1 means the raw probabilities are under-confident but on the correct side of 0.5; scaling then pushes them towards 0 or 1, so a near-zero scaled ECE shows the signal separates these cases at 0.5, not that its probabilities are finely calibrated. Sample sizes are small; see `n`.

## Failures

- `hypothetical_vs_fact`: "Since I live in Vienna, what would I do on weekends?": expected store, got reject (rule `not_memory`, type `intent`)
- `hypothetical_vs_fact`: "Since I live in Auckland, what would I do on weekends?": expected store, got reject (rule `low_durability`, type `fact`)
- `hypothetical_vs_fact`: "Since I live in Dublin, what would I do on weekends?": expected store, got reject (rule `not_memory`, type `intent`)
- `hypothetical_vs_fact`: "Since I live in Kyoto, what would I do on weekends?": expected store, got reject (rule `not_memory`, type `intent`)
- `hypothetical_vs_fact`: "Since I live in Madrid, what would I do on weekends?": expected store, got reject (rule `not_memory`, type `intent`)
- `hypothetical_vs_fact`: "Since I live in Prague, what would I do on weekends?": expected store, got reject (rule `not_memory`, type `intent`)
- `temporary_vs_durable`: "I have owned a house for ten years in Geneva": expected store, got review (rule `sensitive`, type `fact`)
