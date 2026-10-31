#!/bin/bash
# Official signed installers; no Gatekeeper, permissions or policy changes.
set -euo pipefail
SOURCE=$(cd "$(dirname "$0")" && pwd -P)
if [[ "$(uname -s)" != Darwin || "$(uname -m)" != arm64 ]]; then
  echo 'This installer requires Apple Silicon macOS 14 or newer.' >&2; exit 2
fi
if [[ $(sw_vers -productVersion | cut -d. -f1) -lt 14 ]]; then exit 2; fi
if [[ $# -ne 3 || "$3" != I_ACCEPT || ! "$2" =~ ^(core|standard)$ ]]; then
  echo 'Usage: bash setup-online.sh NEW_RUNTIME_DIRECTORY core|standard I_ACCEPT' >&2
  echo 'Installs official Python/R system frameworks (administrator authorization) and private locked package libraries.' >&2
  exit 2
fi
ROOT="$1"
LOCK="$SOURCE/dependencies/macos-arm64-lock.json"
LOCK_SHA=$(shasum -a 256 "$LOCK" | awk '{print $1}')
if [[ -e "$ROOT" && ! -f "$ROOT/.mac-bootstrap" ]]; then echo 'Choose a new, dedicated runtime directory.' >&2; exit 2; fi
mkdir -p "$ROOT"
ROOT=$(cd "$ROOT" && pwd -P)
if [[ -f "$ROOT/.mac-bootstrap" && "$(cat "$ROOT/.mac-bootstrap")" != "$LOCK_SHA" ]]; then echo 'Different dependency lock owns this directory.' >&2; exit 2; fi
printf '%s\n' "$LOCK_SHA" > "$ROOT/.mac-bootstrap"
mkdir -p "$ROOT/cache" "$ROOT/setup-logs"
URL=$(/usr/bin/plutil -extract artifacts.0.url raw -o - "$LOCK")
SHA=$(/usr/bin/plutil -extract artifacts.0.sha256 raw -o - "$LOCK")
NAME=$(/usr/bin/plutil -extract artifacts.0.filename raw -o - "$LOCK")
PKG="$ROOT/cache/${SHA}_${NAME}"
if [[ ! -f "$PKG" ]]; then
  /usr/bin/curl --fail --location --proto '=https' --tlsv1.2 "$URL" -o "$PKG.part"
  [[ "$(shasum -a 256 "$PKG.part" | awk '{print $1}')" == "$SHA" ]] || { echo 'Python SHA256 mismatch; partial retained.' >&2; exit 2; }
  mv "$PKG.part" "$PKG"
fi
[[ "$(shasum -a 256 "$PKG" | awk '{print $1}')" == "$SHA" ]] || { echo 'Cached Python SHA256 mismatch.' >&2; exit 2; }
/usr/sbin/pkgutil --check-signature "$PKG" > "$ROOT/setup-logs/python-signature.txt"
grep -q 'Python Software Foundation' "$ROOT/setup-logs/python-signature.txt"
if [[ ! -f "$ROOT/python-installed.json" ]]; then
  if [[ $(id -u) -eq 0 ]]; then /usr/sbin/installer -pkg "$PKG" -target /; else sudo /usr/sbin/installer -pkg "$PKG" -target /; fi
fi
exec /Library/Frameworks/Python.framework/Versions/3.14/bin/python3.14 -I -B "$SOURCE/tools/macos_setup.py" install --root "$ROOT" --profile "$2"
