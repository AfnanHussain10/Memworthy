---
type: fix
subject: bookshelf
labels: []
sources:
- role: user
  session_id: 24e528bd-3d15-5dd1-80ad-f80d0f346462
  message_id: 20a2d2e0-3c16-592a-93bd-3d094649037f
  text: the import script crashes when a CSV row has an empty ISBN column, please fix it
files:
- scripts/import_books.py
policy: dev-sessions
policy_version: '1.1'
confidence: 0.95
metadata:
  referenced_files:
  - scripts/import_books.py
---

Fixed the importer crash: parse_row called .strip() on a missing ISBN value. Rows with a blank ISBN are now skipped in scripts/import_books.py, and the import tests pass.
