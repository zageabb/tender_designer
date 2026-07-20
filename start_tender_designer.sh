#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

if [ ! -d ".venv" ]; then
  echo "Missing .venv. Create it first with: python3 -m venv .venv"
  exit 1
fi

if [ ! -x ".venv/bin/flask" ]; then
  echo "Missing .venv/bin/flask. Install dependencies first with: .venv/bin/python -m pip install -r requirements.txt"
  exit 1
fi

exec .venv/bin/flask --app app run --host=0.0.0.0 --port=5050
