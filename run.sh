#!/usr/bin/env bash
#
# Run Recall locally.
#
#   ./run.sh          start the dev server with auto-reload
#   ./run.sh test     run the end-to-end smoke tests
#
# On first run this creates a virtualenv in .venv and installs dependencies.
# Works on Linux, macOS, and Git Bash on Windows.
#
set -euo pipefail
cd "$(dirname "$0")"

VENV="${VENV_DIR:-.venv}"

# POSIX venvs put executables in bin/, Windows venvs in Scripts/.
venv_python() {
  if [ -x "$VENV/bin/python" ]; then
    echo "$VENV/bin/python"
  elif [ -x "$VENV/Scripts/python.exe" ]; then
    echo "$VENV/Scripts/python.exe"
  else
    return 0
  fi
}

# First Python on PATH that is new enough to run this app.
find_python() {
  for candidate in python3.12 python3.11 python3 python; do
    command -v "$candidate" >/dev/null 2>&1 || continue
    if "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
      command -v "$candidate"
      return 0
    fi
  done
  return 1
}

PY="$(venv_python)"

# A venv copied between operating systems points at a Python that no longer
# exists (e.g. C:\...\python.exe on Linux). Detect that and rebuild it.
if [ -n "$PY" ] && ! "$PY" -c 'import sys' >/dev/null 2>&1; then
  echo "==> $VENV was built for another platform and cannot run here."
  echo "    Rebuilding it (dependencies will be reinstalled from requirements.txt)."
  rm -rf "$VENV"
  PY=""
fi

if [ -z "$PY" ]; then
  if ! BOOTSTRAP="$(find_python)"; then
    echo "Error: no Python 3.10 or newer found on PATH." >&2
    echo "  Debian/Ubuntu:  sudo apt install python3 python3-venv python3-pip" >&2
    echo "  Fedora:         sudo dnf install python3 python3-pip" >&2
    echo "  Arch:           sudo pacman -S python python-pip" >&2
    exit 1
  fi
  echo "==> Creating virtualenv in $VENV (using $BOOTSTRAP)"
  if ! "$BOOTSTRAP" -m venv "$VENV"; then
    echo "Error: could not create the virtualenv." >&2
    echo "  On Debian/Ubuntu this usually means:  sudo apt install python3-venv" >&2
    exit 1
  fi
  PY="$(venv_python)"
  "$PY" -m pip install --quiet --upgrade pip
fi

# Reinstall whenever requirements.txt changes.
STAMP="$VENV/.requirements-installed"
if [ ! -f "$STAMP" ] || [ requirements.txt -nt "$STAMP" ]; then
  echo "==> Installing dependencies from requirements.txt"
  "$PY" -m pip install --quiet -r requirements.txt
  touch "$STAMP"
fi

if [ ! -f ".env" ]; then
  echo "==> No .env found; copying .env.example -> .env"
  cp .env.example .env
  echo "    Add your GEMINI_API_KEY to .env — until you do, the app runs in"
  echo "    offline heuristic mode and writes lower-quality cards."
fi

if [ "${1:-}" = "test" ]; then
  echo "==> Running smoke tests"
  exec "$PY" smoke_test.py
fi

PORT="${PORT:-8000}"
echo "==> Recall starting on http://localhost:$PORT   (Ctrl-C to stop)"
exec "$PY" -m uvicorn app.main:app --reload --host 0.0.0.0 --port "$PORT"
