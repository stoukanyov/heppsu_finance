#!/bin/bash
# PostToolUse (Write|Edit): feedback запис в паметта без ред „Механизъм:“ се
# връща на модела за поправка.
# Lessons learned Beagle Owner, 11.09.2026 (I14): 6 изрични правила на Ив,
# записани в паметта и нарушени между 1 и 11 дни след записа — текст без
# механизъм. Всяко ново правило казва КАКВО го налага, или изрично признава,
# че е само текст.
set -u
IN=$(cat)
F=$(printf '%s' "$IN" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("tool_input",{}).get("file_path",""))' 2>/dev/null) || exit 0
case "$F" in
  */memory/feedback-*.md) ;;
  *) exit 0 ;;
esac
[[ -f "$F" ]] || exit 0
if ! grep -Eq '^Механизъм:' "$F"; then
  echo "memory_mechanism_check: $F няма ред „Механизъм: <тест/хук/скрипт, който налага правилото>“ или „Механизъм: САМО ТЕКСТ — <защо не е проверимо>“. Правило без механизъм се нарушава (I14). Добави реда." >&2
  exit 2
fi
exit 0
