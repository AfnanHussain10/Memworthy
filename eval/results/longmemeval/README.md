# LongMemEval knowledge-update comparison: pending real run

Status: **pending real run.** No numbers are reported yet.

The runner (`eval/longmemeval.py`) is implemented and unit-tested offline. It needs about 7 LLM calls per question (fact extraction in chunks of 12 sessions, one answer per arm, one grading call) for the 78 knowledge-update questions of `longmemeval_s_cleaned.json` (xiaowu0162/longmemeval-cleaned, MIT). The configured `EXTRACTOR_MODEL` is a free OpenRouter model that was rate-limited upstream (HTTP 429) on 2026-09-25, and the key is on OpenRouter's free tier, which allows about 50 free-model requests per day.

To produce the numbers:

```bash
curl -L -o longmemeval_s_cleaned.json \
  https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned/resolve/main/longmemeval_s_cleaned.json
python eval/longmemeval.py longmemeval_s_cleaned.json --limit 78 --max-llm-calls 600
```

The run resumes from its cache after a rate limit, so with a free-tier key it can be repeated daily until `metrics.json` says `"complete": true`. Design: both arms share one extraction; the baseline stores every fact, the Memworthy arm gates the same facts in chronological order with `personal-memory` (Jev calls recorded to `jev_fixtures.json`); each arm answers from its top-10 BM25 memories; one call grades both answers with LongMemEval's knowledge-update rule.
