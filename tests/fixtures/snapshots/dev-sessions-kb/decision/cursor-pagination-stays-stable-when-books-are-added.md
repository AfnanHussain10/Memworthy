---
type: decision
subject: bookshelf
labels: []
sources:
- role: user
  session_id: 0c8e9520-65b4-5e06-91aa-710a922a9eb8
  message_id: 5f6053a6-afeb-549e-90af-eff82a6e172d
  text: why cursor pagination instead of offset pagination for the books list?
files: []
policy: dev-sessions
policy_version: '1.1'
confidence: 1.0
metadata:
  referenced_files: []
---

Cursor pagination stays stable when books are added while a client is paging, and it avoids slow OFFSET scans on large tables. Offset pagination was rejected for those two reasons.
