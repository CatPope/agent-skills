#!/usr/bin/env bash
# agent-skills installer (macOS / Linux)
#
#   ./install.sh --list
#   ./install.sh --workflow supervisor-worker
#   ./install.sh --status
#
# Links the _core skills plus the chosen workflow's skills into both agent
# skill stores using symlinks. On Windows use install.ps1 instead: plain
# symlinks there need administrator rights, junctions do not.
set -euo pipefail
cd "$(dirname "$0")"
ROOT="$(pwd)"

CLAUDE_DIR="${CLAUDE_SKILLS_DIR:-$HOME/.claude/skills}"
AGENTS_DIR="${AGENTS_SKILLS_DIR:-$HOME/.agents/skills}"
MARKER="$AGENTS_DIR/.agent-skills-active"

WORKFLOW=""; DO_LIST=0; DO_STATUS=0; FORCE=0
while [ $# -gt 0 ]; do
  case "$1" in
    --list)     DO_LIST=1 ;;
    --status)   DO_STATUS=1 ;;
    --force)    FORCE=1 ;;
    --workflow) shift; WORKFLOW="${1:-}" ;;
    *) echo "알 수 없는 인자: $1" >&2; exit 2 ;;
  esac
  shift
done

PY="${PYTHON:-python3}"
command -v "$PY" >/dev/null 2>&1 || PY=python

field () {  # field <json-file> <key>
  "$PY" - "$1" "$2" <<'PYEOF'
import json, sys
d = json.load(open(sys.argv[1], encoding="utf-8"))
v = d.get(sys.argv[2], "")
print(" ".join(v) if isinstance(v, list) else (v if v is not None else ""))
PYEOF
}

if [ "$DO_LIST" = 1 ]; then
  echo; echo "사용 가능한 워크플로우"; echo
  for f in workflows/*.json; do
    printf "  %-20s [%s] %s\n" "$(field "$f" id)" "$(field "$f" status)" "$(field "$f" name)"
    printf "  %-20s   %s\n\n" "" "$(field "$f" summary)"
  done
  echo "설치:  ./install.sh --workflow <id>"; echo
  exit 0
fi

if [ "$DO_STATUS" = 1 ]; then
  if [ -f "$MARKER" ]; then echo "활성 워크플로우: $(cat "$MARKER")"
  else echo "활성 워크플로우 없음 (아직 설치하지 않았습니다)"; fi
  exit 0
fi

[ -n "$WORKFLOW" ] || { echo "--workflow <id> 를 지정하거나 --list 로 목록을 보세요." >&2; exit 2; }
MF="workflows/$WORKFLOW.json"
[ -f "$MF" ] || { echo "알 수 없는 워크플로우: $WORKFLOW  (--list 로 확인)" >&2; exit 2; }
ST="$(field "$MF" status)"
[ "$ST" = "active" ] || { echo "'$WORKFLOW' 는 status=$ST 입니다. 아직 설치할 수 없습니다." >&2; exit 2; }

TARGETS=()
for d in skills/_core/*/; do TARGETS+=("$ROOT/${d%/}"); done
for s in $(field "$MF" skills); do
  p="$ROOT/skills/$WORKFLOW/$s"
  [ -d "$p" ] || { echo "매니페스트에 있으나 폴더가 없습니다: $p" >&2; exit 1; }
  TARGETS+=("$p")
done

mkdir -p "$CLAUDE_DIR" "$AGENTS_DIR"

linked=0; skipped=0; failed=()
for src in "${TARGETS[@]}"; do
  name="$(basename "$src")"
  for dir in "$CLAUDE_DIR" "$AGENTS_DIR"; do
    link="$dir/$name"
    if [ -e "$link" ] || [ -L "$link" ]; then
      if [ -L "$link" ] && [ "$(readlink "$link")" = "$src" ]; then
        skipped=$((skipped+1)); continue
      fi
      # 심링크가 아닌 실제 디렉터리는 --force 로도 지우지 않는다. 안의 내용이 유일본일 수 있다.
      if [ ! -L "$link" ]; then
        failed+=("$link  (실제 디렉터리 — 내용을 확인해 옮기거나 지운 뒤 다시 실행)")
        continue
      fi
      if [ "$FORCE" != 1 ]; then
        echo "다른 곳을 가리키는 링크(건너뜀): $link  -> 교체하려면 --force" >&2
        skipped=$((skipped+1)); continue
      fi
      unlink "$link" 2>/dev/null || true
      if [ -e "$link" ] || [ -L "$link" ]; then
        failed+=("$link  (기존 링크 제거 실패)"); continue
      fi
    fi
    ln -s "$src" "$link" 2>/dev/null || true
    # 만들었다고 가정하지 않는다 — 실제로 그 대상을 가리키는지 확인하고 센다
    if [ -L "$link" ] && [ "$(readlink "$link")" = "$src" ]; then
      linked=$((linked+1))
    else
      failed+=("$link  (링크 생성 실패)")
    fi
  done
done

printf '%s' "$WORKFLOW" > "$MARKER"
echo
echo "설치: $(field "$MF" name)"
echo "  링크 ${linked}개 생성, ${skipped}개 건너뜀, ${#failed[@]}개 실패"
echo "  대상: $CLAUDE_DIR / $AGENTS_DIR"
echo "  스킬: $(for t in "${TARGETS[@]}"; do printf '%s ' "$(basename "$t")"; done)"

if [ "${#failed[@]}" -gt 0 ]; then
  echo
  echo "처리하지 못한 항목 — 이 경로들은 아직 저장소를 가리키지 않습니다:" >&2
  for f in "${failed[@]}"; do echo "  - $f" >&2; done
  echo >&2
  echo "실제 디렉터리는 자동으로 지우지 않습니다. 안에 있는 것이 유일본일 수 있기 때문입니다." >&2
  echo "내용을 확인해 저장소로 옮겼거나 더 필요 없다고 판단되면, 직접 지운 뒤 다시 실행하세요." >&2
  echo >&2
  exit 1
fi
echo
