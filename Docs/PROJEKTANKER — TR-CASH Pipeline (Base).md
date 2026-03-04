PROJEKTANKER — TR-CASH Pipeline (Base)

Ziel
- Automatisierte Verarbeitung von Trade Republic Cash-Kontoauszügen (PDF) zu:
  (a) archiviertem JSON,
  (b) dauerhaftem TR_CASH State (tr_state.json),
  (c) Reports (Jahr/Monat) + Update des global_finance_state.json.

Entry / Trigger
- run_tr_cash_run_from_inbox_pdf.sh prüft:
  /Users/joachimthomas/Documents/Joachim privat/Banken/Trade Republic/INBOX_Auszüge/Kontoauszug.pdf
  -> wenn vorhanden: Start von tr_cash_run.sh (silent/best effort).

Pipeline Orchestrator
- tr_cash_run.sh (CRP: TR Cash Run-Pipeline)
  - Logging: .../Logs/TradeRepublic-Cash/tr_cash_run.log (nur letzter Run bleibt)
  - Notifications: finance_notify.sh (Scope TR_CASH)
  - Always rc=0 nach außen (launchd-freundlich)
  - Steps:
    1) P2J: tr_pdf_2_json.py
       - rc 0 ok, rc 10 no input, rc 20 technical
       - liefert END-Zeile mit dest=..., min=..., max=...
    2) J2S: J2S.py <dest-json>
       - schreibt State:
         ~/Library/Application Support/Finanzen/TR_CASH/tr_state.json
       - loggt: "ingested=N period=YYYY-MM-DD_bis_YYYY-MM-DD"
       - rc 0 updated, rc 10 skip
    3) S2R: tr_reports_from_tr_state.py <years...>
       - Reports nach:
         /Users/joachimthomas/Documents/Joachim privat/Banken/Trade Republic/Reports/<YEAR>/...
       - Update Global:
         ~/Library/Application Support/Finanzen/global_finance_state.json
       - stdout-Logs parsebar (report_updated/global updated)

Konverter (P2J)
- tr_pdf_2_json.py
  - Playwright sync; nutzt lokales Tool:
    .../TradeRepublic-Cash/Trade-Republic-CSV-Excel/index.html (file://)
  - Archivziele:
    JSON: /Users/joachimthomas/Finanzverwaltung/Archiv/TradeRepublic/Cash/Kontobewegungen_JSON
    PDF:  /Users/joachimthomas/Documents/Joachim privat/Banken/Trade Republic/Auszüge

State-Ingest (aktuell)
- J2S.py
  - Minimal-Ingest, UID sha1 über Pflichtfelder (16 chars)
  - Stats: txCount, min/max BookingDate, currentBalance, lastPeriodFrom/To

Legacy/Referenz
- tr_state_from_json.py
  - Alternative/robustere Ingest-Variante (ENV TR_CASH_INBOX_JSON)
  - aktuell nicht im Runner verdrahtet, aber als Fallback/Referenz behalten.

Leitprinzipien
- Deterministisch + idempotent (UID-Dedup)
- Launchd ruhig halten (Runner rc=0), Fehler/Status via Notifications & Log
- Parsebare stdout-Zeilen für Step-Verkettung (P2J END, J2S ingested/period, S2R report/global).