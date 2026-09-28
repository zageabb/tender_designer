#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

if [ ! -x ".venv/bin/python" ]; then
  echo "Missing .venv/bin/python. Create the virtual environment and install requirements first."
  exit 1
fi

export TENDER_DESIGNER_PROCESS_ROLE=mailbox
exec .venv/bin/python mailbox_daemon.py
