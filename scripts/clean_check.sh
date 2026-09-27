#!/usr/bin/env bash
# Run acceptance commands against a clean copy of the files git would commit.
# Usage: scripts/clean_check.sh 'cmd1' 'cmd2' ...   (commands run inside the copy's .venv)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEST="${CLEAN_DIR:-$(mktemp -d)}/memworthy"
rm -rf "$DEST" && mkdir -p "$DEST"
cd "$ROOT"
git ls-files --cached --others --exclude-standard -z | xargs -0 -I{} rsync -R "{}" "$DEST/"
cd "$DEST"
PY="$(pyenv prefix "$(cat .python-version)")/bin/python"
"$PY" -m venv .venv
.venv/bin/pip install -q --upgrade pip >/dev/null
.venv/bin/pip install -q -e ".[dev,jev,mem0]" 2>&1 | grep -v "Cache entry" || true
export PATH="$DEST/.venv/bin:$PATH"
status=0
for cmd in "$@"; do
  echo "\$ $cmd"
  if bash -o pipefail -c "$cmd"; then echo "-> ok"; else echo "-> FAILED"; status=1; fi
done
echo "clean copy: $DEST"
exit $status
