#!/bin/bash
# PreToolUse (Bash): комит върху main или detached HEAD се отказва.
#
# Lessons learned Beagle Owner, 11.09.2026 (I6): 33+5 комита на main в клиента,
# 3 в бекенда, 3 нощни reset-а от Ив — при пет записани правила. Текстът не
# стигна; това е механизмът. Промотирането (ff-merge на origin/dev, push,
# тагове) остава разрешено — то е пътят към production след одобрение.
#
# Изход 2 = Claude Code отказва командата и показва stderr на модела.
set -u
INPUT=$(cat)
CMD=$(printf '%s' "$INPUT" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("tool_input",{}).get("command",""))' 2>/dev/null) || exit 0
CWD=$(printf '%s' "$INPUT" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("cwd",""))' 2>/dev/null)

# Интересува ни само `git commit` (с или без -C <път>).
printf '%s' "$CMD" | grep -Eq '(^|[;&|[:space:]])git([[:space:]]+-C[[:space:]]+[^[:space:]]+)?[[:space:]]+commit([[:space:]]|$)' || exit 0

REPO=$(printf '%s' "$CMD" | sed -nE 's/.*git[[:space:]]+-C[[:space:]]+("([^"]+)"|([^[:space:]]+)).*commit.*/\2\3/p' | head -1)
if [[ -z "$REPO" ]]; then
  REPO=$(printf '%s' "$CMD" | sed -nE 's/.*(^|[;&|[:space:]])cd[[:space:]]+("([^"]+)"|([^[:space:]]+)).*/\3\4/p' | head -1)
fi
[[ -z "$REPO" ]] && REPO="$CWD"
[[ -d "$REPO" ]] || exit 0
git -C "$REPO" rev-parse --git-dir >/dev/null 2>&1 || exit 0
BRANCH=$(git -C "$REPO" branch --show-current 2>/dev/null)

if [[ -z "$BRANCH" ]]; then
  echo "guard_git: $REPO е в detached HEAD — комит се отказва. Първо: git -C '$REPO' checkout dev (или feature клон)." >&2
  exit 2
fi
if [[ "$BRANCH" == "main" || "$BRANCH" == "master" ]]; then
  echo "guard_git: $REPO е на '$BRANCH' — комит на production клона се отказва (правило на Ив, 06.09.2026: работи в dev; main се мести само с ff-merge след потвърден билд). Първо: git -C '$REPO' checkout dev." >&2
  exit 2
fi
exit 0
