#!/bin/bash
set -euo pipefail
SOURCE=$(cd "$(dirname "$0")" && pwd -P)
if [[ $# -lt 3 ]]; then echo 'Usage: bash launch.sh RUNTIME core|standard|docling check|meta [arguments]' >&2; exit 2; fi
ROOT="$1"; PROFILE="$2"; shift 2
exec "$ROOT/python/venv/bin/python" -I -B "$SOURCE/tools/macos_setup.py" launch --root "$ROOT" --profile "$PROFILE" -- "$@"
