#!/bin/bash
set -euo pipefail
SOURCE=$(cd "$(dirname "$0")" && pwd -P)
if [[ $# -ne 2 || "$2" != I_ACCEPT ]]; then echo 'Usage: bash setup-offline.sh NEW_RUNTIME_DIRECTORY I_ACCEPT' >&2; exit 2; fi
export META_OFFLINE_CACHE="${META_OFFLINE_PAYLOAD:-$SOURCE/offline-payload}/cache"
[[ -d "$META_OFFLINE_CACHE" ]] || { echo 'Missing offline payload/cache' >&2; exit 2; }
exec bash "$SOURCE/setup-online.sh" "$1" docling I_ACCEPT
