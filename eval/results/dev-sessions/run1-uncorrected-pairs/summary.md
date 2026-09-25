# dev-sessions v1.1: contrast-pair evaluation

Judge `recorded`, model `jev-1.13.0`, 236 cases in 118 pairs (`dev-sessions.yaml`), generated 2026-09-25.

| Metric | Value |
| --- | --- |
| Action accuracy | 87.3% |
| Pair consistency | 75.4% |
| Judge errors | 0 |
| Median Jev call latency (at recording) | 1013 ms (p90 1140 ms) |
| Median input tokens / cost per candidate | 682 / $0.000029 |

## By category

| Category | Cases | Accuracy | Pair consistency |
| --- | --- | --- | --- |
| abandoned_vs_final | 6 | 100.0% | 100.0% |
| concluded_vs_open | 24 | 100.0% | 100.0% |
| endorsed_vs_proposed | 52 | 71.2% | 46.2% |
| grounded_vs_ungrounded | 52 | 100.0% | 100.0% |
| noise_vs_work | 8 | 100.0% | 100.0% |
| project_vs_generic | 10 | 70.0% | 40.0% |
| secret_vs_clean | 24 | 100.0% | 100.0% |
| supersede_vs_new | 8 | 100.0% | 100.0% |
| verified_vs_unverified | 52 | 76.9% | 53.8% |

## Calibration

| Signal | n | ECE raw | ECE temperature-scaled (2-fold CV) | T (all data) |
| --- | --- | --- | --- | --- |
| concluded | 12 | 0.047 | 0.000 | 0.32 |
| endorsed | 52 | 0.260 | 0.283 | 2.11 |
| project_specific | 7 | 0.123 | 0.000 | 0.14 |
| superseded_later | 6 | 0.132 | 0.000 | 0.16 |
| worth_keeping | 8 | 0.286 | 0.001 | 0.05 |

## Failures

- `verified_vs_unverified`: "Changed the retry limit to fix the flaky upload": expected store_labeled, got reject (rule `noise`, type `fix`)
- `verified_vs_unverified`: "Changed the connection timeout to fix the flaky upload": expected store_labeled, got reject (rule `noise`, type `fix`)
- `verified_vs_unverified`: "Changed the batch size to fix the flaky upload": expected store_labeled, got reject (rule `noise`, type `task`)
- `verified_vs_unverified`: "Changed the lock order to fix the flaky upload": expected store_labeled, got reject (rule `noise`, type `fix`)
- `verified_vs_unverified`: "Changed the default page size to fix the flaky upload": expected store_labeled, got reject (rule `noise`, type `fix`)
- `verified_vs_unverified`: "Changed the image resize filter to fix the flaky upload": expected store_labeled, got reject (rule `noise`, type `fix`)
- `verified_vs_unverified`: "Changed the upload chunk size to fix the flaky upload": expected store_labeled, got reject (rule `noise`, type `fix`)
- `verified_vs_unverified`: "Changed the worker concurrency to fix the flaky upload": expected store_labeled, got reject (rule `noise`, type `task`)
- `verified_vs_unverified`: "Changed the DNS cache TTL to fix the flaky upload": expected store_labeled, got reject (rule `noise`, type `task`)
- `verified_vs_unverified`: "Changed the request body limit to fix the flaky upload": expected store_labeled, got reject (rule `noise`, type `fix`)
- `verified_vs_unverified`: "Changed the S3 multipart threshold to fix the flaky upload": expected store_labeled, got reject (rule `noise`, type `fix`)
- `verified_vs_unverified`: "Changed the gzip level to fix the flaky upload": expected store_labeled, got reject (rule `noise`, type `task`)
- `endorsed_vs_proposed`: "Decided to use SQLite for the new service.": expected review/store_labeled, got store (rule `rules[9]`, type `decision`)
- `endorsed_vs_proposed`: "Decided to use Redis streams for the new service.": expected review/store_labeled, got store (rule `rules[9]`, type `decision`)
- `endorsed_vs_proposed`: "Decided to use a cron job for the new service.": expected store, got reject (rule `noise`, type `decision`)
- `endorsed_vs_proposed`: "Decided to use a cron job for the new service.": expected review/store_labeled, got store (rule `rules[9]`, type `decision`)
- `endorsed_vs_proposed`: "Decided to use server-side rendering for the new service.": expected review/store_labeled, got store (rule `rules[9]`, type `decision`)
- `endorsed_vs_proposed`: "Decided to use feature flags for the new service.": expected review/store_labeled, got store (rule `rules[9]`, type `decision`)
- `endorsed_vs_proposed`: "Decided to use a message queue for the new service.": expected review/store_labeled, got store (rule `rules[9]`, type `decision`)
- `endorsed_vs_proposed`: "Decided to use UUIDv7 keys for the new service.": expected review/store_labeled, got store (rule `rules[9]`, type `decision`)
- `endorsed_vs_proposed`: "Decided to use a read replica for the new service.": expected review/store_labeled, got store (rule `rules[9]`, type `decision`)
- `endorsed_vs_proposed`: "Decided to use OpenTelemetry tracing for the new service.": expected review/store_labeled, got store (rule `rules[9]`, type `decision`)
- `endorsed_vs_proposed`: "Decided to use a monorepo for the new service.": expected review/store_labeled, got store (rule `rules[9]`, type `decision`)
- `endorsed_vs_proposed`: "Decided to use htmx for the new service.": expected review/store_labeled, got store (rule `rules[9]`, type `decision`)
- `endorsed_vs_proposed`: "Decided to use a CDN cache for the new service.": expected review/store_labeled, got store (rule `rules[9]`, type `decision`)
- `endorsed_vs_proposed`: "Decided to use row-level security for the new service.": expected review/store_labeled, got store (rule `rules[9]`, type `decision`)
- `endorsed_vs_proposed`: "Decided to use event sourcing for the new service.": expected review/store_labeled, got store (rule `rules[9]`, type `decision`)
- `project_vs_generic`: "In this repo, order IDs are ULIDs so they sort by creation time.": expected store, got store_labeled (rule `ungrounded`, type `explanation`)
- `project_vs_generic`: "Our API returns 409 when two clients edit the same draft, and the client retries once.": expected store, got store_labeled (rule `ungrounded`, type `explanation`)
- `project_vs_generic`: "Our search index is rebuilt nightly because incremental updates missed deletions.": expected store, got store_labeled (rule `unverified_work`, type `fix`)
