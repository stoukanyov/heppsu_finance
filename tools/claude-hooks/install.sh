#!/bin/bash
# Инсталира трите хука за ВСИЧКИ Claude Code сесии на тази машина:
#   ~/.claude/hooks/*.sh  +  записи в ~/.claude/settings.json
#
# Пуска го Ив (веднъж). Claude сесията няма право сама да променя собствените
# си предпазители — това е нарочно и правилно.
#
# Проверка след инсталация: в нова сесия „git -C <repo на main> commit“ трябва
# да бъде отказан с текст „guard_git: … е на 'main'“.
set -euo pipefail
SRC="$(cd "$(dirname "$0")" && pwd)"
DST="$HOME/.claude/hooks"
SETTINGS="$HOME/.claude/settings.json"

mkdir -p "$DST"
for f in guard_git.sh prompt_guard.sh memory_mechanism_check.sh; do
  install -m 0755 "$SRC/$f" "$DST/$f"
  echo "  $DST/$f"
done

python3 - "$SETTINGS" "$DST" <<'PY'
import json, sys, pathlib, time
path = pathlib.Path(sys.argv[1]); hooks_dir = sys.argv[2]
data = json.loads(path.read_text()) if path.exists() else {}
backup = path.with_suffix(f".json.bak-{time.strftime('%Y%m%d-%H%M%S')}")
if path.exists():
    backup.write_text(path.read_text()); print(f"  резервно копие: {backup}")
hooks = data.setdefault("hooks", {})
want = {
    "PreToolUse":       {"matcher": "Bash",       "cmd": f"{hooks_dir}/guard_git.sh"},
    "UserPromptSubmit": {"matcher": "",           "cmd": f"{hooks_dir}/prompt_guard.sh"},
    "PostToolUse":      {"matcher": "Write|Edit", "cmd": f"{hooks_dir}/memory_mechanism_check.sh"},
}
for event, spec in want.items():
    entries = hooks.setdefault(event, [])
    if any(h.get("command") == spec["cmd"] for e in entries for h in e.get("hooks", [])):
        print(f"  {event}: вече е там"); continue
    entry = {"hooks": [{"type": "command", "command": spec["cmd"]}]}
    if spec["matcher"]:
        entry["matcher"] = spec["matcher"]
    entries.append(entry); print(f"  {event}: добавен {spec['cmd']}")
path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
print(f"  записано: {path}")
PY
echo "Готово. Хуковете важат за новите сесии."
