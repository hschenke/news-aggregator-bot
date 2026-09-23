# 📰 News Aggregator Bot

Ein autonomer, KI-gestützter News-Kurator, der Nachrichten aus deinen bevorzugten Quellen (RSS, Blogs, News-Feeds) aggregiert, mit einem LLM (Google Gemini) intelligent zusammenfasst und dir bereitstellt:
1. **Weg A:** Vollautomatisch als **formatierte tägliche E-Mail** (jeden Morgen via GitHub Actions).
2. **Weg B:** Als **interaktive 24/7 Web-App** (kostenlos gehostet auf Streamlit Community Cloud).

> 💡 **Beide Wege funktionieren parallel!** Du kannst dich morgens per E-Mail briefen lassen und tagsüber jederzeit mobil in der Web-App nachlesen oder ein frisches Ad-hoc-Briefing anfordern.

---

## 💡 Systemübersicht

| Kriterium | Eigene App (GitHub Actions + Streamlit Cloud) | Grok Bot / Custom GPTs | No-Code Tools (Make / Zapier) |
| :--- | :--- | :--- | :--- |
| **Kosten** | **0 € / Monat** (Free-Tiers reichen völlig) | Monatliches Abo (X Premium, ChatGPT Plus) | Kostenlos nur stark eingeschränkt |
| **Autarkie (24/7)** | Vollautomatische Cloud-Ausführung | Nur innerhalb der jeweiligen Plattform | Benötigt Bezahl-Tarife oder Server |
| **Quellenvielfalt** | Beliebige RSS-Feeds, Nischenblogs, APIs | Eingeschränkt | RSS und APIs möglich |
| **Zustellung** | **E-Mail-Postfach** (Weg A) + **Web-App** (Weg B) | In-App-Chat | E-Mail, Slack, etc. |
| **Kontrolle & Anpassung** | 100% Kontrolle über Prompts, Filter & Design | Reglementiert | Visuelle Klick-Logik |

---

## 🚀 Die zwei Bereitstellungswege

```
               ┌───────────────────────────────┐
               │    config/sources.yaml        │
               │   (Deine RSS-Quellen)         │
               └──────────────┬────────────────┘
                              │
                      [ Quellensammlung ]
                              │
               ┌──────────────┴───────────────┐
               ▼                              ▼
      【 Weg A: E-Mail 】             【 Weg B: Web-App 】
      GitHub Actions Cron            Streamlit Community Cloud
      Jeden Morgen um 07:00          24/7 im Browser & am Smartphone
               │                              │
               ▼                              ▼
        Google Gemini                  Google Gemini
               │                              │
               ▼                              ▼
      HTML-Mail im Postfach          Live Dashboard & Suche
```

---

### 📬 Weg A: Täglicher E-Mail-Digest (GitHub Actions)

- **Ablauf**: Ein Cronjob (`.github/workflows/daily_digest.yml`) startet jeden Morgen automatisch auf GitHub.
- **Versand**: Kostenlos über [Resend](https://resend.com) (bis zu 3.000 Mails/Monat gratis) oder eigenes SMTP.
- **Kosten**: 0 € (GitHub Actions bietet 2.000 kostenlose Minuten/Monat).

#### Setup für Weg A:
1. Repository zu GitHub pushen.
2. In GitHub navigieren zu: **Settings > Secrets and variables > Actions**.
3. Folgende Secrets anlegen:
   - `GEMINI_API_KEY`: Dein Gemini API Key ([Google AI Studio](https://aistudio.google.com/))
   - `RESEND_API_KEY`: Dein Resend API Key ([resend.com](https://resend.com))
   - `EMAIL_TO`: Deine Empfänger-Adresse

---

### 🌐 Weg B: Web-App (Streamlit Community Cloud)

- **Ablauf**: Die Web-App wird direkt aus diesem GitHub-Repository auf [Streamlit Community Cloud](https://share.streamlit.io/) gehostet.
- **Vorteile**:
  - Live-Dashboard mit Statistiken & Quellenübersicht.
  - Button für Ad-hoc **KI-Briefing auf Knopfdruck**.
  - Volltextsuche und Kategoriefilter für alle Artikel.
  - Download des Briefings als Markdown-Datei.
  - Funktioniert perfekt auf dem Smartphone (als "Zum Startbildschirm hinzufügen" wie eine native App).
- **Kosten**: 0 € (Kostenloses Hosting durch Streamlit/Snowflake).

#### Schritt-für-Schritt Setup für Weg B:
1. Gehe auf **[share.streamlit.io](https://share.streamlit.io/)** und melde dich mit deinem GitHub-Konto an.
2. Klicke auf **"Create app"** (bzw. "Deploy an app").
3. Wähle dein Repository aus:
   - **Repository:** `dein-github-name/news-aggregator-bot`
   - **Branch:** `main`
   - **Main file path:** `streamlit_app.py`
4. Klicke auf **Advanced settings** (oder nach Deployment unter App Settings > Secrets):
   Füge deine Secrets im TOML-Format ein:
   ```toml
   GEMINI_API_KEY = "AIzaSy..."
   GEMINI_MODEL = "gemini-3.5-flash-lite"
   ```
5. Klicke auf **Deploy!**
6. Nach ca. 1-2 Minuten ist deine Web-App live unter einer URL wie `https://dein-news-bot.streamlit.app` erreichbar.

> 📱 **Smartphone-Tipp**: Öffne die generierte Streamlit-URL in Safari (iOS) oder Chrome (Android) und wähle im Teilen-Menü **"Zum Home-Bildschirm"**. Schon hast du deine eigene News-App als Icon auf deinem Smartphone!

---

## 📁 Projektstruktur

```text
news-aggregator-bot/
├── .github/
│   └── workflows/
│       └── daily_digest.yml       # Weg A: Automatischer Cloud-Cronjob
├── .streamlit/
│   ├── config.toml                # Weg B: Modernes Theme & Server-Settings
│   └── secrets.toml.example       # Weg B: Vorlage für Streamlit Cloud Secrets
├── config/
│   └── sources.yaml               # RSS-Feeds und Kategorien
├── src/
│   ├── aggregator.py              # Sammelt & filtert RSS-News
│   ├── summarizer.py              # LLM-Zusammenfassung via Gemini API
│   ├── notifier.py                # HTML-Mail Generator & Versand
│   ├── main.py                    # Pipeline-Skript für Weg A (E-Mail)
│   └── webapp.py                  # Streamlit Dashboard für Weg B
├── streamlit_app.py               # Root Entrypoint für Streamlit Cloud
├── requirements.txt               # Python-Abhängigkeiten
├── .env.example                   # Vorlage für lokale Umgebungsvariablen
└── README.md
```

---

## 🛠️ Lokale Ausführung

### 1. Installation
```bash
# Virtuelle Umgebung erstellen
python -m venv .venv

# Aktivieren (Windows PowerShell):
.venv\Scripts\Activate.ps1
# Mac / Linux:
source .venv/bin/activate

# Pakete installieren
pip install -r requirements.txt
```

### 2. Lokale .env Datei
```bash
cp .env.example .env
```
Trage deinen `GEMINI_API_KEY` ein.

### 3. Starten

**Weg A lokal testen (erzeugt auch eine HTML-Vorschau in `output/`):**
```bash
python src/main.py
```

**Weg B lokal testen (startet die Web-App):**
```bash
streamlit run streamlit_app.py
```
*(Die App öffnet sich automatisch unter `http://localhost:8501`)*
