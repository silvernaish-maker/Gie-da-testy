#!/usr/bin/env bash
# Symulacja GEM: tworzy środowisko Pythona, pobiera dane ze stooq i otwiera raport.
set -e
cd "$(dirname "$0")"
if [ ! -d .venv ]; then
  echo "Tworzę środowisko Pythona..."
  python3 -m venv .venv
fi
. .venv/bin/activate
python -m pip install -q --disable-pip-version-check -r requirements.txt
python run_gem.py "$@"
open reports/gem_raport.html 2>/dev/null || xdg-open reports/gem_raport.html 2>/dev/null || true
