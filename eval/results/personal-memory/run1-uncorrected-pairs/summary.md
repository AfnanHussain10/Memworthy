# personal-memory v1.1: contrast-pair evaluation

Judge `recorded`, model `jev-1.13.0`, 274 cases in 126 pairs (`personal-memory.yaml`), generated 2026-09-25.

| Metric | Value |
| --- | --- |
| Action accuracy | 94.5% |
| Pair consistency | 88.1% |
| Judge errors | 0 |
| Median Jev call latency (at recording) | 998 ms (p90 1079 ms) |
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
| user_vs_third_party | 38 | 78.9% | 57.9% |

## Calibration

| Signal | n | ECE raw | ECE temperature-scaled (2-fold CV) | T (all data) |
| --- | --- | --- | --- | --- |
| about_subject | 38 | 0.118 | 0.000 | 0.08 |
| durable | 100 | 0.165 | 0.000 | 0.05 |
| retraction | 9 | 0.057 | 0.000 | 0.27 |

## Failures

- `hypothetical_vs_fact`: "Since I live in Vienna, what would I do on weekends?": expected store, got reject (rule `not_memory`, type `intent`)
- `hypothetical_vs_fact`: "Since I live in Auckland, what would I do on weekends?": expected store, got reject (rule `low_durability`, type `fact`)
- `hypothetical_vs_fact`: "Since I live in Dublin, what would I do on weekends?": expected store, got reject (rule `not_memory`, type `intent`)
- `hypothetical_vs_fact`: "Since I live in Kyoto, what would I do on weekends?": expected store, got reject (rule `not_memory`, type `intent`)
- `hypothetical_vs_fact`: "Since I live in Madrid, what would I do on weekends?": expected store, got reject (rule `not_memory`, type `intent`)
- `hypothetical_vs_fact`: "Since I live in Prague, what would I do on weekends?": expected store, got reject (rule `not_memory`, type `intent`)
- `user_vs_third_party`: "I is allergic to peanuts": expected store, got review (rule `sensitive`, type `fact`)
- `user_vs_third_party`: "Hassan is training for a marathon": expected review, got reject (rule `not_memory`, type `temporary`)
- `user_vs_third_party`: "Maria is training for a marathon": expected review, got reject (rule `not_memory`, type `temporary`)
- `user_vs_third_party`: "Kenji is training for a marathon": expected review, got reject (rule `not_memory`, type `temporary`)
- `user_vs_third_party`: "Fatima is training for a marathon": expected review, got reject (rule `not_memory`, type `temporary`)
- `user_vs_third_party`: "Lucas is training for a marathon": expected review, got reject (rule `not_memory`, type `temporary`)
- `user_vs_third_party`: "Aisha is training for a marathon": expected review, got reject (rule `not_memory`, type `temporary`)
- `user_vs_third_party`: "Tom is training for a marathon": expected review, got reject (rule `not_memory`, type `temporary`)
- `temporary_vs_durable`: "I have owned a house for ten years in Geneva": expected store, got review (rule `sensitive`, type `fact`)
