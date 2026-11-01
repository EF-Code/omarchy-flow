#!/usr/bin/env bash
# Exercise UI process failure paths while keeping persistence in the real backend.
set -euo pipefail
mode="${0##*/}"
if [[ "${1:-}" == qml ]]; then
  case "${2:-}" in
    list-models)
      case "$mode" in
        timeout) exec sleep 10 ;;
        malformed) echo null; exit 0 ;;
        *) exit 1 ;;
      esac
      ;;
    status)
      if [[ "$mode" == bad-status ]]; then
        echo '{"model":"whisper-base.en"}'
        exit 0
      fi
      ;;
    set-model)
      if [[ "$mode" == write-fails ]]; then exit 1; fi
      if [[ "$mode" == slow-save ]]; then sleep 0.3; fi
      ;;
  esac
fi
fixture_root="$(cd "$(dirname "$(realpath "$0")")/.." && pwd)"
exec "$fixture_root/scripts/real-flowctl" "$@"
