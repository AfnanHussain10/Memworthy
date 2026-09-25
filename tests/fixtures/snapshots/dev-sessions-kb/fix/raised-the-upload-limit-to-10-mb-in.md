---
type: fix
subject: bookshelf
labels:
- unverified
sources:
- role: user
  session_id: fe3f4f2d-a224-50a0-82de-705cd1c4935d
  message_id: null
  text: the book cover upload fails for PNG files larger than 5 MB, please fix
files:
- app/uploads.py
policy: dev-sessions
policy_version: '1.1'
confidence: 0.56
metadata:
  referenced_files:
  - app/uploads.py
---

Raised the upload limit to 10 MB in app/uploads.py, which should fix large PNG cover uploads; test_large_png still fails, so the proxy limit may also need changing.
