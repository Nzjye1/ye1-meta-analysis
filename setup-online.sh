#!/bin/bash
# Official signed installers; no Gatekeeper, permissions or policy changes.
set -euo pipefail
SOURCE=$(cd "$(dirname "$0")" && pwd -P)
if [[ "$(uname -s)" != Darwin || "$(uname -m)" != arm64 ]]; then
  echo 'This installer requires Apple Silicon macOS 14 or newer.' >&2; exit 2
fi
if [[ $(sw_vers -productVersion | cut -d. -f1) -lt 14 ]]; then exit 2; fi
if [[ $# -ne 3 || "$3" != I_ACCEPT || ! "$2" =~ ^(core|standard|docling)$ ]]; then
  echo 'Usage: bash setup-online.sh NEW_RUNTIME_DIRECTORY core|standard|docling I_ACCEPT' >&2
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
  if [[ -n "${META_OFFLINE_CACHE:-}" ]]; then cp "$META_OFFLINE_CACHE/${SHA}_${NAME}" "$PKG.part"; else /usr/bin/curl --fail --location --proto '=https' --tlsv1.2 "$URL" -o "$PKG.part"; fi
  [[ "$(shasum -a 256 "$PKG.part" | awk '{print $1}')" == "$SHA" ]] || { echo 'Python SHA256 mismatch; partial retained.' >&2; exit 2; }
  mv "$PKG.part" "$PKG"
fi
[[ "$(shasum -a 256 "$PKG" | awk '{print $1}')" == "$SHA" ]] || { echo 'Cached Python SHA256 mismatch.' >&2; exit 2; }
/usr/sbin/pkgutil --check-signature "$PKG" > "$ROOT/setup-logs/python-signature.txt"
grep -q 'Python Software Foundation' "$ROOT/setup-logs/python-signature.txt"
if [[ ! -f "$ROOT/python-installed.json" ]]; then
  if [[ $(id -u) -eq 0 ]]; then /usr/sbin/installer -pkg "$PKG" -target /; else sudo /usr/sbin/installer -pkg "$PKG" -target /; fi
fi
PYTHON=/Library/Frameworks/Python.framework/Versions/3.14/bin/python3.14
# Official python.org installers require certificate setup. Bootstrap the fixed
# certifi wheel with the system curl trust store, then use its CA bundle only in
# this process/runtime, without modifying system trust or an existing Python.
IFS=$'\t' read -r CA_URL CA_SHA CA_NAME <<< "$("$PYTHON" -I -c 'import json,sys; a=next(a for a in json.load(open(sys.argv[1]))["artifacts"] if a["name"]=="certifi"); print(a["url"],a["sha256"],a["filename"],sep="\t")' "$LOCK")"
CA_WHEEL="$ROOT/cache/${CA_SHA}_${CA_NAME}"
if [[ ! -f "$CA_WHEEL" ]]; then
  if [[ -n "${META_OFFLINE_CACHE:-}" ]]; then cp "$META_OFFLINE_CACHE/${CA_SHA}_${CA_NAME}" "$CA_WHEEL.part"; else /usr/bin/curl --fail --location --proto '=https' --tlsv1.2 "$CA_URL" -o "$CA_WHEEL.part"; fi
  [[ "$(shasum -a 256 "$CA_WHEEL.part" | awk '{print $1}')" == "$CA_SHA" ]] || { echo 'CA wheel SHA256 mismatch.' >&2; exit 2; }
  mv "$CA_WHEEL.part" "$CA_WHEEL"
fi
[[ "$(shasum -a 256 "$CA_WHEEL" | awk '{print $1}')" == "$CA_SHA" ]] || { echo 'Cached CA wheel SHA256 mismatch.' >&2; exit 2; }
"$PYTHON" -I -c 'import sys,zipfile,pathlib; pathlib.Path(sys.argv[2]).write_bytes(zipfile.ZipFile(sys.argv[1]).read("certifi/cacert.pem"))' "$CA_WHEEL" "$ROOT/bootstrap-ca.pem"
export SSL_CERT_FILE="$ROOT/bootstrap-ca.pem"
exec "$PYTHON" -I -B "$SOURCE/tools/macos_setup.py" install --root "$ROOT" --profile "$2"
