# Projekt-Richtlinien für News Aggregator Bot

## Automatischer Start-Ablauf
- **Automatisches `git pull`**: Führe zu Beginn jeder neuen Konversation bzw. als allererste Aktion bei der Bearbeitung der ersten Benutzeranfrage in diesem Projekt immer automatisch `git pull` aus, um das lokale Repository auf den neuesten Stand zu bringen.
- Gib dem Benutzer kurz Rückmeldung über den Status/Ergebnis der Aktualisierung.

## Automatischer Abschluss-Ablauf
- **Automatisches Committen & `git push`**: Nach jeder abgeschlossenen Umsetzung von Änderungen oder neuen Features immer sofort alle Änderungen committen und zu GitHub (`git push origin main`) hochladen, damit der Benutzer die Änderungen sofort online auf GitHub und Streamlit Cloud sehen kann.
- Gib dem Benutzer eine Bestätigung mit dem Commit-Hash und der Nachricht.

## Proaktive Versions-Tag Empfehlung (Semantic Versioning)
- **Tag-Bedarf proaktiv prüfen**: Prüfe nach dem Commit oder bei Erreichen eines logischen Meilensteins (z. B. neues Feature abgeschlossen, UI-Redesign, wichtiger Bugfix oder vor größeren Refactorings), ob sich ein neuer Versions-Tag lohnt (`git describe --tags` / `git log <letzter-tag>..HEAD`).
- **Proaktiver Vorschlag**: Wenn signifikante Änderungen oder ein Meilenstein seit dem letzten Tag vorliegen, weise den Benutzer kurz darauf hin und schlage eine konkrete Versionsnummer nach Semantic Versioning vor:
  - **Minor (`v0.X.0`)**: Bei neuen Features, neuen Seiten/Modulen oder signifikanten UI/Architektur-Erweiterungen.
  - **Patch (`v0.X.Y`)**: Bei Bugfixes, Dependency-/Workflow-Updates oder kleineren Detailanpassungen.
- **Tag auf Bestätigung setzen**: Fragt der Benutzer nach oder bestätigt den Vorschlag, erstelle sofort den annotierten Tag und pushe ihn mit `git push origin <tag>`.


