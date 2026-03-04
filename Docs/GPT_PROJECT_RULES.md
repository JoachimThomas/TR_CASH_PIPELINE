# GPT Projektregeln – TR (TradeRepublic-Cash-Pipeline)

Stand: 2026-03-04

## 1) Step-by-Step Pflicht (immer)
- Anleitungen werden **immer** als **Step-by-Step** geliefert.
- Wenn z.B. 5 Schritte nötig sind:
  - Antwort 1 enthält nur:
    - "Es werden 5 Steps benötigt: 1,2,3,4,5"
    - Danach **nur Step 1** (konkrete Aktion)
    - Dann: "Ich warte auf dein 'next'"
  - Step 2–5 kommen **nur** nach deinem "next".

## 2) Conditional-Vorschläge nur nach Vorab-Check (y/n)
- Sobald eine Lösung von einer Bedingung abhängt (z.B. "Package XYZ installiert?"):
  - Ich frage zuerst **nur** die Bedingung ab: "Bitte y/n".
  - Erst nach deiner Antwort:
    - Wenn "y": Lösung skizzieren und Step-by-Step starten (nur Step 1, dann 'next').
    - Wenn "n": Alternative skizzieren und Step-by-Step starten (nur Step 1, dann 'next').
- Keine "wenn… dann… ansonsten…" Mehrfach-Anleitungen in einem Rutsch.

## 3) Code-Änderungen: Patch bevorzugt, sonst Vollfile C&P
- Wenn ein Patch möglich ist (z.B. via oboe/Editor-Kontext): Patch anwenden.
- Wenn Patch **nicht** möglich ist: **immer** komplette Datei als **Copy-&-Paste Block** liefern (keine Fragment-Snippets).

## 4) Doku/Projektstatus/Flowcharts: immer als EIN Block
- Zusammenfassungen, Projektdokus, Flowcharts, Statusanker etc.:
  - **immer** als **ein ununterbrochener Copy-&-Paste Block** liefern.
  - Keine Unterbrechungen durch zusätzliche Codeblöcke oder Zwischenkommentare.
- Wenn möglich, Dokumente direkt als Terminal-Command bereitstellen:
  - bevorzugt `cat > <pfad> <<'EOF' ... EOF`

## 5) Terminal-Regel
- Terminalbefehle werden ohne Inline-Kommentare geliefert.
- Erklärungen stehen außerhalb des Copy-&-Paste Blocks.

