#!/usr/bin/env bash
# Load dashboard/local-dev defaults for this checkout.
# Usage: source dashboard/ports.sh  (from bash or zsh)

# Handle both bash and zsh
if [ -n "${BASH_SOURCE[0]:-}" ]; then
  _PORTS_SCRIPT="${BASH_SOURCE[0]}"
elif [ -n "${(%):-%x}" 2>/dev/null ]; then
  _PORTS_SCRIPT="${(%):-%x}"
else
  _PORTS_SCRIPT="$0"
fi

REPO_ROOT="$(cd "$(dirname "$_PORTS_SCRIPT")/.." && pwd)"
ENV_FILE="$REPO_ROOT/.env"
_PORTS_SOURCED=0

if (return 0 2>/dev/null); then
  _PORTS_SOURCED=1
fi

if [ -f "$ENV_FILE" ]; then
  while IFS='=' read -r key val; do
    case "$key" in
      DASHBOARD_BE_PORT|DASHBOARD_FE_PORT)
        val="${val%%#*}"
        val="$(echo "$val" | xargs)"
        eval "export ${key}=\"\${${key}:-${val}}\""
        ;;
    esac
  done < "$ENV_FILE"
fi

if command -v shasum >/dev/null 2>&1; then
  _PORTS_HASH="$(printf '%s' "$REPO_ROOT" | shasum -a 256 | awk '{print $1}')"
elif command -v sha256sum >/dev/null 2>&1; then
  _PORTS_HASH="$(printf '%s' "$REPO_ROOT" | sha256sum | awk '{print $1}')"
else
  _PORTS_HASH="00000000"
fi

_PORTS_SLOT=$(( 16#$(printf '%s' "$_PORTS_HASH" | cut -c1-8) % 5000 ))
_DEFAULT_BE_PORT=$(( 23000 + _PORTS_SLOT ))
_DEFAULT_FE_PORT=$(( 28000 + _PORTS_SLOT ))

export DASHBOARD_BE_PORT="${DASHBOARD_BE_PORT:-$_DEFAULT_BE_PORT}"
export DASHBOARD_FE_PORT="${DASHBOARD_FE_PORT:-$_DEFAULT_FE_PORT}"

# If executed (not sourced), print for eval.
if [ "$_PORTS_SOURCED" -eq 0 ]; then
  echo "export DASHBOARD_BE_PORT=$DASHBOARD_BE_PORT"
  echo "export DASHBOARD_FE_PORT=$DASHBOARD_FE_PORT"
fi

unset _PORTS_SCRIPT
unset _PORTS_SOURCED
unset _PORTS_HASH
unset _PORTS_SLOT
unset _DEFAULT_BE_PORT
unset _DEFAULT_FE_PORT
