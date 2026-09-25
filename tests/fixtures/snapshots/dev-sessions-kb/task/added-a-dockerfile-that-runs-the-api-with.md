---
type: task
subject: bookshelf
labels: []
sources:
- role: user
  session_id: 06228e83-1d9e-5e04-94c1-470d2346fb4b
  message_id: null
  text: write a Dockerfile so we can deploy the bookshelf API on a small VPS
files:
- Dockerfile
policy: dev-sessions
policy_version: '1.1'
confidence: 1.0
metadata:
  referenced_files:
  - Dockerfile
---

Added a Dockerfile that runs the API with gunicorn on port 8000 from python:3.12-slim; the image builds.
