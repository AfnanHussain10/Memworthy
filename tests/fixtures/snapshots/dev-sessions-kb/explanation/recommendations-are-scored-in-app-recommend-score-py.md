---
type: explanation
subject: bookshelf
labels: []
sources:
- role: user
  session_id: 410ba72b-5567-5c41-9563-6acd3ae2bb76
  message_id: null
  text: explain how the recommendation scoring works in this codebase, step by step
files:
- app/recommend/score.py
- app/recommend/features.py
policy: dev-sessions
policy_version: '1.1'
confidence: 0.99
metadata:
  referenced_files:
  - app/recommend/score.py
  - app/recommend/features.py
---

Recommendations are scored in app/recommend/score.py: app/recommend/features.py computes genre overlap, author affinity and recency, score() weights them 0.5, 0.3 and 0.2, and the top 10 books are returned.
