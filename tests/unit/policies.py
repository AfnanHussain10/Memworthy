"""Small policies used across unit tests."""

BASIC = """\
policy: basic
version: 1.0
types:
  fact: A durable fact
  temporary: A short-lived state
  intent: A plan
signals:
  from_user: {check: source_is_user}
  secret: {check: secret_scan}
  timing: {check: date_parse}
  durable: {noul: "Will this still be true in a year?"}
  mood: {choice: "What mood?", options: {happy: Happy, sad: Sad}}
  sensitivity: {score: "How sensitive?", levels: [Low, Medium, High]}
  only_intent: {noul: "Is it firm?", applies_to: [intent]}
rules:
  - {name: secrets, when: "secret", then: redact}
  - {name: not_user, when: "not from_user", then: reject}
  - {name: firm_intent, when: "type == 'intent' and only_intent > 0.8", then: review}
  - {name: temp, when: "type in ['temporary', 'intent']", then: reject}
  - {name: future, when: "timing == 'future'", then: reject}
  - {name: weak, when: "durable < 0.6", then: reject}
  - {name: sensitive, when: "sensitivity >= 1.5", then: review}
  - {name: upd, when: "conflict and conflict.p > 0.7", then: update}
  - {else: store}
tests:
  - {input: "I live in Lahore", expect: store}
"""
