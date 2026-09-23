# 📰 News Aggregator Bot

Ein autonomer, KI-gestützter News-Kurator, der Nachrichten aus deinen bevorzugten Quellen (RSS, Blogs, News-Feeds) aggregiert, mit einem LLM (Google Gemini) intelligent zusammenfasst und dir täglich als **formatierte E-Mail** oder interaktive **Web-App** bereitstellt.

---

## 💡 Architektur- & Systemvergleich

| Kriterium | Eigene App (Python + GitHub Actions) *(Empfohlen)* | Grok Bot / Custom GPTs | No-Code Tools (Make / Zapier / n8n) |
| :--- | :--- | :--- | :--- |
| **Kosten** | **0 € / Monat** (Free-Tiers reichen völlig) | Monatliches Abo (z.B. X Premium / ChatGPT Plus) | Kostenlos nur mit sehr strengen Limitierungen |
| **Autarkie (24/7)** | Läuft komplett autark über Cloud-Cronjob (GitHub Actions) | Nur innerhalb der jeweiligen Plattform | Benötigt Cloud-Abo oder eigenen Server (z.B. VPS) |
| **Quellenvielfalt** | Beliebige RSS-Feeds, Nischenblogs, APIs | Eingeschränkt (Grok vorrangig X/Twitter) | RSS und APIs möglich |
| **Zustellung** | Tägliche E-Mail, Web-App oder Telegram/Discord | In-App-Chat / Benachrichtigung | E-Mail, Slack, etc. |
| **Kontrolle & Anpassung** | 100% Anpassung von Prompt, Filterung und Design | Stark reglementiert | Gut anpassbar, aber visuelle Klick-Logik |

---

## 🚀 Zwei Betriebsmodi

### 1. Modus: Autarke tägliche E-Mail (GitHub Actions)
- **Wie es funktioniert**: Ein zeitgesteuerter Workflow (`.github/workflows/daily_digest.yml`) startet jeden Morgen automatisch auf GitHub-Servern.
- **Vorteil**: Du musst keinen eigenen Server mieten und keinen Computer laufen lassen.
- **Kosten**: 0 € (GitHub Actions bietet 2.000 kostenlose Minuten/Monat, der Bot braucht ~15 Minuten/Monat).
- **Versand**: Über [Resend](https://resend.com) (3.000 Mails/Monat gratis) oder eigenes SMTP (z. B. Gmail App-Passwort).

### 2. Modus: Interaktive Web-App (Streamlit)
- **Wie es funktioniert**: Eine mobile-optimierte Web-Oberfläche (`src/webapp.py`), auf der du jederzeit frische News abrufen und ein Live-KI-Briefing generieren kannst.
- **Hosting**: Kostenlos mit 1-Klick über [Streamlit Community Cloud](https://share.streamlit.io/) direkt aus deinem GitHub-Repo verknüpfen.

---

## 📁 Projektstruktur

```text
news-aggregator-bot/
├── .github/
│   └── workflows/
│       └── daily_digest.yml   # Automatischer 24/7 Cloud-Cronjob
├── config/
│   └── sources.yaml           # Deine RSS-Feeds und Kategorien
├── src/
│   ├── aggregator.py          # Holt & filtert Nachrichten aus RSS-Feeds
│   ├── summarizer.py          # KI-Zusammenfassung via Gemini API
│   ├── notifier.py            # Generiert HTML-Digest & sendet E-Mails
│   ├── main.py                # Haupt-Pipeline für den E-Mail-Digest
│   └── webapp.py              # Interaktives Streamlit-Web-Dashboard
├── requirements.txt           # Python-Abhängigkeiten
├── .env.example               # Vorlage für API-Keys
└── README.md
```

---

## 🛠️ Schnellstart (Lokal)

### 1. Abhängigkeiten installieren
```bash
python -m venv .venv
# Windows PowerShell:
.venv\Scripts\Activate.ps1
# Mac/Linux:
source .venv/bin/activate

pip install -r requirements.txt
```

### 2. Konfiguration anpassen
Kopiere `.env.example` zu `.env`:
```bash
cp .env.example .env
```
Füge deine API-Keys ein:
- **`GEMINI_API_KEY`**: Kostenlos bei [Google AI Studio](https://aistudio.google.com/) erstellen.
- **`RESEND_API_KEY`**: Kostenlos bei [Resend](https://resend.com) registrieren (oder SMTP-Daten angeben).

Passe deine gewünschten Quellen in `config/sources.yaml` an.

### 3. Ausführen

**E-Mail-Pipeline testen:**
```bash
python src/main.py
```
*(Hinweis: Erstellt zusätzlich immer eine Vorschau-Datei in `output/daily_digest.html`, die du direkt im Browser öffnen kannst!)*

**Web-App starten:**
```bash
streamlit run src/webapp.py
```

---

## ☁️ Autarkes Online-Deployment (Schritt für Schritt)

1. **Repository auf GitHub pushen** (privat oder öffentlich).
2. **Secrets hinterlegen**:
   - Gehe in deinem GitHub-Repository auf **Settings > Secrets and variables > Actions**.
   - Füge `GEMINI_API_KEY`, `RESEND_API_KEY` und `EMAIL_TO` als Repository Secrets hinzu.
3. **Fertig!** Der Bot läuft ab sofort jeden Morgen vollautomatisch und schickt dir dein persönliches News-Briefing.
