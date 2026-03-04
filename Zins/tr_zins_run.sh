#!/bin/zsh
set -euo pipefail

IN_DIR="/Users/joachimthomas/Documents/Joachim privat/Banken/Trade Republic/INBOX_ZINS"
PY="/Users/joachimthomas/Finanzverwaltung/Programme/Traderepublic/TradeRepublic-Cash/Zins/tr_interest_revenue_to_globaltaxes_state_from_zinsabrechnung.py"

LOG_DIR="/Users/joachimthomas/Finanzverwaltung/Programme/Logs/TradeRepublic-Cash"
LOG_FILE="${LOG_DIR}/tr_zins_run.log"

LOCK_DIR="/tmp/tr_zins_run.lockdir"
DEBOUNCE_FILE="/tmp/tr_zins_run.debounce"
DEBOUNCE_SECONDS=15

mkdir -p "${LOG_DIR}"

now_epoch="$(date +%s)"

if [ -f "${DEBOUNCE_FILE}" ]; then
  last="$(cat "${DEBOUNCE_FILE}" 2>/dev/null || echo 0)"
  if [ "${last}" -gt 0 ]; then
    delta="$(( now_epoch - last ))"
    if [ "${delta}" -lt "${DEBOUNCE_SECONDS}" ]; then
      exit 0
    fi
  fi
fi

echo "${now_epoch}" > "${DEBOUNCE_FILE}" 2>/dev/null || true

if ! mkdir "${LOCK_DIR}" 2>/dev/null; then
  exit 0
fi
trap 'rmdir "${LOCK_DIR}" 2>/dev/null || true' EXIT

if [ ! -d "${IN_DIR}" ]; then
  exit 0
fi

if ! find "${IN_DIR}" -maxdepth 1 -type f -name "*.pdf" -print -quit | grep -q .; then
  exit 0
fi

ts="$(date '+%Y-%m-%d %H:%M:%S')"
{
  echo "MARK | ${ts} | START"
  /usr/bin/env python3 "${PY}"
  rc="$?"
  echo "MARK | ${ts} | END rc=${rc}"
  exit "${rc}"
} >> "${LOG_FILE}" 2>&1
