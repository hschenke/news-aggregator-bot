# Projekt-Richtlinien für News Aggregator Bot

## Automatischer Start-Ablauf
- **Automatisches `git pull`**: Führe zu Beginn jeder neuen Konversation bzw. als allererste Aktion bei der Bearbeitung der ersten Benutzeranfrage in diesem Projekt immer automatisch `git pull` aus, um das lokale Repository auf den neuesten Stand zu bringen.
- Gib dem Benutzer kurz Rückmeldung über den Status/Ergebnis der Aktualisierung.

## Automatischer Abschluss-Ablauf
- **Automatisches Committen & `git push`**: Nach jeder abgeschlossenen Umsetzung von Änderungen oder neuen Features immer sofort alle Änderungen committen und zu GitHub (`git push origin main`) hochladen, damit der Benutzer die Änderungen sofort online auf GitHub und Streamlit Cloud sehen kann.
- Gib dem Benutzer eine Bestätigung mit dem Commit-Hash und der Nachricht.

