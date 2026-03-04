# TR-Zins Parser – launchd Watcher

## Zweck
Watcher auf INBOX_ZINS, startet Runner mit Debounce+Lock. Verarbeitet Zins-/Dividenden-PDFs und schreibt in global_capital_revenues_taxes.json.

## WatchPath
/Users/joachimthomas/Documents/Joachim privat/Banken/Trade Republic/INBOX_ZINS

## Dateien
- de.joachimthomas.trcash.zins.plist
- tr_zins_run.sh
- Python:
  /Users/joachimthomas/Finanzverwaltung/Programme/Traderepublic/TradeRepublic-Cash/Zins/tr_interest_revenue_to_globaltaxes_state_from_zinsabrechnung.py

## Logs
/Users/joachimthomas/Finanzverwaltung/Programme/Logs/TradeRepublic-Cash/tr_zins_run.log
/Users/joachimthomas/Finanzverwaltung/Programme/Logs/TradeRepublic-Cash/tr_zins_launchd.out.log
/Users/joachimthomas/Finanzverwaltung/Programme/Logs/TradeRepublic-Cash/tr_zins_launchd.err.log

## Install
cp Docs/Zins/launchd/de.joachimthomas.trcash.zins.plist "$HOME/Library/LaunchAgents/"
launchctl bootstrap gui/$(id -u) "$HOME/Library/LaunchAgents/de.joachimthomas.trcash.zins.plist"
launchctl enable gui/$(id -u)/de.joachimthomas.trcash.zins

## Uninstall
launchctl bootout gui/$(id -u) "$HOME/Library/LaunchAgents/de.joachimthomas.trcash.zins.plist"
rm -f "$HOME/Library/LaunchAgents/de.joachimthomas.trcash.zins.plist"
