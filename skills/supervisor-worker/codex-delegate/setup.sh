#!/usr/bin/env bash
# Bootstrap check for codex-delegate. Idempotent; installs nothing.
# codex_task.py uses the Python standard library only, so there are no deps to install.
set -e
cd "$(dirname "$0")"

PY="${CODEX_DELEGATE_PY:-python3}"
command -v "$PY" >/dev/null 2>&1 || PY=python
"$PY" -c "import sys; sys.exit(0 if sys.version_info >= (3,9) else 1)" \
  || { echo "[codex-delegate] need Python >= 3.9"; exit 1; }
"$PY" -m py_compile scripts/codex_task.py

if command -v codex >/dev/null 2>&1; then
  echo "[codex-delegate] codex CLI: $(command -v codex)"
else
  echo "[codex-delegate] WARNING: codex CLI not on PATH - the helper will fall back to a known install path."
fi
echo "[codex-delegate] ready."
