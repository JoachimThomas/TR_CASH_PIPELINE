PROJEKTANKER — TR-Cash: Zins-/Dividenden-Parser (launchd) — Stand 2026-03-04

Ziel
- Verarbeitung von TR-Zins-/Dividenden-Abrechnungs-PDFs aus INBOX_ZINS
- Archivierung der PDFs
- Upsert in global_capital_revenues_taxes.json
- Benachrichtigung via finance_notify.sh (OK/FAIL)

Input
- INBOX: /Users/joachimthomas/Documents/Joachim privat/Banken/Trade Republic/INBOX_ZINS
- Dateien: *.pdf

Core Script
- /Users/joachimthomas/Finanzverwaltung/Programme/Traderepublic/TradeRepublic-Cash/Zins/tr_interest_revenue_to_globaltaxes_state_from_zinsabrechnung.py
  - Parser-Blöcke:
    - ÜBERSICHT (Gross pro Asset-Zeile)
    - ABRECHNUNG - ZINSEN (kest/soli/net)
    - ABRECHNUNG - DIVIDENDE (kest/soli/net)
    - BUCHUNG (Gutschrift nach Steuern) -> Synthetic Entry incomeType="Buchung"
  - Archiv: /Users/joachimthomas/Finanzverwaltung/Archiv/TradeRepublic/Cash/Zinsabrechnungen
  - Global State: ~/Library/Application Support/Finanzen/global_capital_revenues_taxes.json
  - Returncodes:
    - 0 OK verarbeitet
    - 10 OK keine neuen PDFs
    - 20 FAIL teilweise/Fehler

Automation (launchd)
- LaunchAgent: ~/Library/LaunchAgents/de.joachimthomas.trcash.zins.plist
  - WatchPaths: /Users/joachimthomas/Documents/Joachim privat/Banken/Trade Republic/INBOX_ZINS
  - RunAtLoad: true
  - Program: tr_zins_run.sh

Runner
- /Users/joachimthomas/Finanzverwaltung/Programme/Traderepublic/TradeRepublic-Cash/Zins/tr_zins_run.sh
  - Debounce: 15s
  - Single-Instance Lock: /tmp/tr_zins_run.lockdir
  - Log: /Users/joachimthomas/Finanzverwaltung/Programme/Logs/TradeRepublic-Cash/tr_zins_run.log
  - launchd logs:
    - /Users/joachimthomas/Finanzverwaltung/Programme/Logs/TradeRepublic-Cash/tr_zins_launchd.out.log
    - /Users/joachimthomas/Finanzverwaltung/Programme/Logs/TradeRepublic-Cash/tr_zins_launchd.err.log

RunNow (manuell)
- launchctl kickstart -k gui/$(id -u)/de.joachimthomas.trcash.zins
- oder Runner direkt:
  /Users/joachimthomas/Finanzverwaltung/Programme/Traderepublic/TradeRepublic-Cash/Zins/tr_zins_run.sh
