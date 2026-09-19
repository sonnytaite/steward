#!/bin/zsh
# Weekly steward run. Always produces the facts (deterministic); then tries a headless
# judgement pass with Claude Code. If the headless pass is unavailable, the facts are
# still there for the next interactive /steward:brief.
set -u
ROOT="${0:A:h:h}"
VAULT="${STEWARD_VAULT:-$HOME/Projects/second-brain}"
DATE=$(date +%Y-%m-%d)
LOG="$VAULT/surfaces/steward/weekly.log"
mkdir -p "$VAULT/surfaces/steward/briefs"
{
  echo "== $(date -u +%FT%TZ) steward-weekly start"
  python3 "$ROOT/rails/steward.py" --config "$ROOT/steward.config.json" brief --save >/dev/null && echo "facts saved for $DATE"
  if command -v claude >/dev/null 2>&1; then
    cd "$VAULT" && claude -p "/steward:brief --headless --date $DATE" --allowedTools "Read,Grep,Glob,Bash(python3 *),Agent,Write" 2>&1 | tail -20
    echo "headless pass exit: $?"
  else
    echo "claude not on PATH; facts only"
  fi
  cd "$VAULT" && git add surfaces/steward >/dev/null 2>&1 && git commit -q -m "steward: weekly facts $DATE" >/dev/null 2>&1 && git push -q >/dev/null 2>&1 && echo "committed"
  echo "== end"
} >> "$LOG" 2>&1
