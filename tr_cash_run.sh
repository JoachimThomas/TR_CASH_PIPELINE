#!/bin/zsh
# shellcheck shell=bash
set -euo pipefail

# ============================================================
# TR Cash – Run-Pipeline (CRP)
#   Launchd triggers when INBOX PDF arrives.
#   Flow:
#     1) P2J: PDF -> JSON (tool via Playwright), validate + archive JSON + archive PDF
#     2) J2S: archived JSON -> state
#     3) S2R: state -> reports + global
#   Always exits rc=0 (launchd stays quiet).
#   Alerts/Notis are handled via finance_notify.sh.
# ============================================================

# ---- Python (fixed) ----
PY="/Library/Frameworks/Python.framework/Versions/3.14/bin/python3"

# ---- Scripts ----
P2J="/Users/joachimthomas/Finanzverwaltung/Programme/Traderepublic/TradeRepublic-Cash/tr_pdf_2_json.py"
J2S="/Users/joachimthomas/Finanzverwaltung/Programme/Traderepublic/TradeRepublic-Cash/J2S.py"
S2R="/Users/joachimthomas/Finanzverwaltung/Programme/Traderepublic/TradeRepublic-Cash/tr_reports_from_tr_state.py"

# ---- Logging ----
LOG="/Users/joachimthomas/Finanzverwaltung/Programme/Logs/TradeRepublic-Cash/tr_cash_run.log"

LOG_ANCHOR="CRP | START TR-CASH-RUN | run_id="

logcut_keep_last_run() {
    local f="$1"
    [[ -f "$f" ]] || return 0
    local last_line
    last_line="$(/usr/bin/grep -nF "$LOG_ANCHOR" "$f" | /usr/bin/tail -n 1 | /usr/bin/cut -d: -f1 || true)"
    [[ -n "$last_line" ]] || return 0
    /usr/bin/tail -n +"$last_line" "$f" >"${f}.tmp" && /bin/mv "${f}.tmp" "$f"
}

logcut_keep_last_run "$LOG"
mkdir -p "$(dirname "$LOG")"
exec > >(tee -a "$LOG") 2>&1

ts() { date '+%Y-%m-%d %H:%M:%S'; }
logline() { echo "[$(ts)] CRP | $*"; }

RUN_ID="TRCASH_$(date '+%Y%m%d_%H%M%S')"
export RUN_ID

# ---- Notify ----
NOTIFY="/Users/joachimthomas/Finanzverwaltung/Programme/Global/finance_notify.sh"
CALLER="TR-Cash-Run-Pipeline"

n() {
    # usage: n LEVEL MESSAGE
    "$NOTIFY" "TR_CASH" "$1" "$2" "$CALLER" >/dev/null 2>&1 || true
}

alert() {
    # one-shot alert, no extra noti spam
    n "FAIL" "$1"
}

# ============================================================
# Start
# ============================================================
logline "START TR-CASH-RUN | run_id=${RUN_ID}"
n "OK" "Start TR-CASH-RUN"

# ============================================================
# Step 1: P2J (PDF -> JSON archived + PDF saved)
#   rc 0  = ok (END line contains dest=... min=... max=...)
#   rc 10 = no input / no usable json (normal end)
#   rc 20 = technical (may alert)
# ============================================================
if [[ ! -f "$P2J" ]]; then
    alert "P2J fehlt: $P2J"
    logline "END TR-CASH-RUN | result=fail_missing_p2j | rc=0 | run_id=${RUN_ID}"
    exit 0
fi

set +e
P2J_OUT="$($PY "$P2J" 2>&1)"
P2J_RC=$?
set -e

echo "$P2J_OUT"

if [[ $P2J_RC -eq 10 ]]; then
    logline "END TR-CASH-RUN | result=no_input | rc=0 | run_id=${RUN_ID}"
    n "OK" "Ende TR-CASH-RUN: kein neuer Auszug"
    exit 0
fi

if [[ $P2J_RC -ne 0 ]]; then
    alert "P2J Fehler (rc=$P2J_RC)"
    logline "END TR-CASH-RUN | result=fail_p2j | rc=0 | run_id=${RUN_ID}"
    exit 0
fi

# Parse DESTPATH + MIN/MAX from P2J END line
END_LINE="$(echo "$P2J_OUT" | /usr/bin/grep -E 'P2J \| END ' | /usr/bin/tail -n 1)"
DESTPATH="$(echo "$END_LINE" | /usr/bin/sed -n 's/.*dest=\([^|]*\).*/\1/p' | /usr/bin/xargs)"
MIN_DATE="$(echo "$END_LINE" | /usr/bin/sed -n 's/.*min=\([^|]*\).*/\1/p' | /usr/bin/xargs)"
MAX_DATE="$(echo "$END_LINE" | /usr/bin/sed -n 's/.*max=\([^|]*\).*/\1/p' | /usr/bin/xargs)"

if [[ -z "$DESTPATH" || ! -f "$DESTPATH" ]]; then
    alert "P2J lieferte kein gültiges dest=..."
    logline "END TR-CASH-RUN | result=fail_p2j_no_dest | rc=0 | run_id=${RUN_ID}"
    exit 0
fi

# Noti: Zeitraum gelesen
if [[ -n "${MIN_DATE:-}" && -n "${MAX_DATE:-}" ]]; then
    n "INFO" "Kontobewegungen vom: ${MIN_DATE}_bis_${MAX_DATE} gelesen."
fi

# ============================================================
# Step 2: J2S (archived json -> state)
#   rc 0  = updated
#   rc 10 = skipped/already
#   else = alert
# ============================================================
if [[ ! -f "$J2S" ]]; then
    alert "J2S fehlt: $J2S"
    logline "END TR-CASH-RUN | result=fail_missing_j2s | rc=0 | run_id=${RUN_ID}"
    exit 0
fi

logline "INFO j2s_call | json=$DESTPATH"
set +e
J2S_OUT="$($PY "$J2S" "$DESTPATH" 2>&1)"
J2S_RC=$?
set -e

echo "$J2S_OUT"

if [[ $J2S_RC -eq 10 ]]; then
    n "INFO" "State war bereits aktuell"
    logline "END TR-CASH-RUN | result=skipped_state_already | rc=0 | run_id=${RUN_ID}"
    n "OK" "Ende TR-CASH-RUN"
    exit 0
elif [[ $J2S_RC -ne 0 ]]; then
    alert "J2S Fehler (rc=$J2S_RC)"
    logline "END TR-CASH-RUN | result=fail_j2s | rc=0 | run_id=${RUN_ID}"
    exit 0
fi

# ------------------------------------------------------------
# Parse J2S output:
#   - NEW_TX from:  "[..] J2S | ingested=73 period=YYYY-MM-DD_bis_YYYY-MM-DD"
#   - PERIOD from:  same line
# ------------------------------------------------------------
parse_j2s_ingested() {
    local out="$1"
    local v
    v="$(echo "$out" | /usr/bin/grep -E '^\[[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}\] J2S \| ingested=' |
        /usr/bin/sed -n 's/.*ingested=\([0-9][0-9]*\).*/\1/p' |
        /usr/bin/tail -n 1)"
    [[ -n "$v" ]] && echo "$v" || echo "0"
}

parse_j2s_period() {
    local out="$1"
    echo "$out" | /usr/bin/grep -E '^\[[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}\] J2S \| ingested=' |
        /usr/bin/sed -n 's/.*period=\([^ ]*\).*/\1/p' |
        /usr/bin/tail -n 1
}

NEW_TX="$(parse_j2s_ingested "$J2S_OUT")"
PERIOD="$(parse_j2s_period "$J2S_OUT")"

# Noti: State aktualisiert (nur wenn wirklich neue TX)
if [[ "${NEW_TX:-0}" -gt 0 ]]; then
    if [[ -n "$PERIOD" ]]; then
        n "INFO" "State aktualisiert (+${NEW_TX}) | period=${PERIOD}"
    else
        n "INFO" "State aktualisiert (+${NEW_TX})"
    fi
fi

# Wenn keine neuen TX: Ende (kein S2R, kein Global)
if [[ "${NEW_TX:-0}" -le 0 ]]; then
    logline "END TR-CASH-RUN | result=skipped_no_new_tx | rc=0 | run_id=${RUN_ID}"
    n "OK" "Ende TR-CASH-RUN"
    exit 0
fi

# ============================================================
# Step 3: S2R (state -> reports + global)
#  - derive target years from PERIOD and pass as args
#  - if no PERIOD -> end (rc=856 logged), no reports
# ============================================================
if [[ ! -f "$S2R" ]]; then
    alert "S2R fehlt: $S2R"
    logline "END TR-CASH-RUN | result=fail_missing_s2r | rc=0 | run_id=${RUN_ID}"
    exit 0
fi

if [[ -z "$PERIOD" ]]; then
    logline "END TR-CASH-RUN | result=no_period_for_reports | rc=856 | run_id=${RUN_ID}"
    n "OK" "Ende TR-CASH-RUN (keine Report-Periode)"
    exit 0
fi

# PERIOD format: YYYY-MM-DD_bis_YYYY-MM-DD
FROM_Y="${PERIOD%%-*}"
TO_PART="${PERIOD##*_bis_}"
TO_Y="${TO_PART%%-*}"

YEARS=()
y="$FROM_Y"
while [[ "$y" -le "$TO_Y" ]]; do
    YEARS+=("$y")
    y=$((y + 1))
done

logline "INFO s2r_call | years=${YEARS[*]}"

set +e
S2R_OUT="$("$PY" "$S2R" "${YEARS[@]}" 2>&1)"
S2R_RC=$?
set -e

echo "$S2R_OUT"

# ------------------------------------------------------------
# Parse S2R output -> Noti(s)
# Current S2R logs we support:
#   [S2R] report_updated | year=YYYY rows=N
#   [S2R] reports_updated | years=YYYY[,YYYY...] ... rows=N   (fallback)
#   [S2R] global updated | asOf=YYYY-MM-DD value=12345.67
# ------------------------------------------------------------
parse_s2r_year() {
    # echoes YYYY or ""
    local out="$1"
    echo "$out" | /usr/bin/grep -E '\[S2R\] report_updated \| year=[0-9]{4} rows=[0-9]+' 2>/dev/null |
        /usr/bin/sed -n 's/.*year=\([0-9]\{4\}\) rows=.*/\1/p' |
        /usr/bin/tail -n 1 || true
}

parse_s2r_year_rows() {
    # echoes integer rows (defaults to 0)
    local out="$1"
    local v
    v="$(echo "$out" | /usr/bin/grep -E '\[S2R\] report_updated \| year=[0-9]{4} rows=[0-9]+' 2>/dev/null |
        /usr/bin/sed -n 's/.*rows=\([0-9][0-9]*\).*/\1/p' |
        /usr/bin/tail -n 1 || true)"
    [[ -n "$v" ]] && echo "$v" || echo "0"
}

parse_s2r_years() {
    # echoes years string like "2024" or "2024,2025,2026" or ""
    local out="$1"
    echo "$out" | /usr/bin/grep -E '\[S2R\] reports_updated \| years=[0-9]{4}([,][0-9]{4})* .*rows=[0-9]+' 2>/dev/null |
        /usr/bin/sed -n 's/.*years=\([^ ]*\) .*/\1/p' |
        /usr/bin/tail -n 1 || true
}

parse_s2r_years_rows() {
    # echoes integer rows (defaults to 0)
    local out="$1"
    local v
    v="$(echo "$out" | /usr/bin/grep -E '\[S2R\] reports_updated \| years=[0-9]{4}([,][0-9]{4})* .*rows=[0-9]+' 2>/dev/null |
        /usr/bin/sed -n 's/.*rows=\([0-9][0-9]*\).*/\1/p' |
        /usr/bin/tail -n 1 || true)"
    [[ -n "$v" ]] && echo "$v" || echo "0"
}

parse_s2r_global_value() {
    # echoes value like 83514.32 or ""
    local out="$1"
    echo "$out" | /usr/bin/grep -E '\[S2R\] global updated \| asOf=[0-9]{4}-[0-9]{2}-[0-9]{2} value=[0-9]+(\.[0-9]+)?' 2>/dev/null |
        /usr/bin/sed -n 's/.*value=\([0-9][0-9]*\(\.[0-9][0-9]*\)?\).*/\1/p' |
        /usr/bin/tail -n 1 || true
}

# Fire Noti based on S2R log
S2R_YEAR="$(parse_s2r_year "$S2R_OUT")"
if [[ -n "$S2R_YEAR" ]]; then
    S2R_ROWS="$(parse_s2r_year_rows "$S2R_OUT")"
    n "INFO" "Reports für ${S2R_YEAR} mit ${S2R_ROWS} TX aktualisiert."
else
    S2R_YEARS="$(parse_s2r_years "$S2R_OUT")"
    if [[ -n "$S2R_YEARS" ]]; then
        S2R_ROWS="$(parse_s2r_years_rows "$S2R_OUT")"
        FIRST_Y="${S2R_YEARS%%,*}"
        LAST_Y="${S2R_YEARS##*,}"
        if [[ "$FIRST_Y" == "$LAST_Y" ]]; then
            n "INFO" "Reports für ${FIRST_Y} mit ${S2R_ROWS} TX aktualisiert."
        else
            n "INFO" "Reports von ${FIRST_Y} bis ${LAST_Y} mit ${S2R_ROWS} TX aktualisiert."
        fi
    fi
fi

S2R_GVAL="$(parse_s2r_global_value "$S2R_OUT")"
if [[ -n "$S2R_GVAL" ]]; then
    n "INFO" "Global updated -> Value ${S2R_GVAL}"
fi

# Success end
logline "END TR-CASH-RUN | result=ok | rc=0 | run_id=${RUN_ID}"
n "OK" "Ende TR-CASH-RUN"
exit 0
