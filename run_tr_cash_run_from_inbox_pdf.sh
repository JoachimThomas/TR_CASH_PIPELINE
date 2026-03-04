#!/bin/zsh
# shellcheck shell=bash
set -euo pipefail

INBOX_PDF="/Users/joachimthomas/Documents/Joachim privat/Banken/Trade Republic/INBOX_Auzüge/Kontoauszug.pdf"
CR="/Users/joachimthomas/Finanzverwaltung/Programme/Traderepublic/TradeRepublic-Cash/tr_cash_run.sh"

# Nur loslaufen, wenn das erwartete PDF wirklich existiert
[[ -f "$INBOX_PDF" ]] || exit 0

# CR starten (best effort, keine UI)
"$CR" >/dev/null 2>&1 || true
exit 0
