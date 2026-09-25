import os
import sys
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from datetime import datetime
import requests
from dotenv import load_dotenv

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

load_dotenv()


def markdown_to_html_email(markdown_content: str) -> str:
    """Wandelt einfaches Markdown in ein sauberes, responsives HTML-Email-Template um."""
    # Einfache Markdown-Konvertierung falls markdown Paket nicht installiert
    try:
        import markdown
        body_html = markdown.markdown(markdown_content, extensions=["extra", "tables"])
    except ImportError:
        # Minimaler Fallback für Überschriften, Links und Listen
        import re
        body_html = markdown_content
        body_html = re.sub(r"^### (.*)$", r"<h3>\1</h3>", body_html, flags=re.MULTILINE)
        body_html = re.sub(r"^## (.*)$", r"<h2>\1</h2>", body_html, flags=re.MULTILINE)
        body_html = re.sub(r"^# (.*)$", r"<h1>\1</h1>", body_html, flags=re.MULTILINE)
        body_html = re.sub(r"\*\*(.*?)\*\*", r"<strong>\1</strong>", body_html)
        body_html = re.sub(r"\[(.*?)\]\((.*?)\)", r'<a href="\2" target="_blank" style="color:#2563eb;text-decoration:underline;">\1</a>', body_html)
        body_html = body_html.replace("\n", "<br>")

    current_date = datetime.now().strftime("%d.%m.%Y")

    html_template = f"""<!DOCTYPE html>
<html lang="de">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Dein Daily News Digest</title>
  <style>
    body {{
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
      line-height: 1.6;
      color: #1f2937;
      background-color: #f3f4f6;
      margin: 0;
      padding: 20px 0;
    }}
    .container {{
      max-width: 680px;
      margin: 0 auto;
      background: #ffffff;
      border-radius: 12px;
      overflow: hidden;
      box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
    }}
    .header {{
      background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%);
      background-color: #1e293b;
      color: #ffffff !important;
      padding: 28px 32px;
      text-align: left;
    }}
    .header h1 {{
      margin: 0 0 6px 0;
      font-size: 24px;
      font-weight: 700;
      letter-spacing: -0.02em;
      color: #ffffff !important;
    }}
    .header p {{
      margin: 0;
      color: #94a3b8 !important;
      font-size: 14px;
    }}
    .content {{
      padding: 32px;
    }}
    .content h1, .content h2, .content h3 {{
      color: #0f172a;
      letter-spacing: -0.01em;
    }}
    h2 {{
      border-bottom: 2px solid #e2e8f0;
      padding-bottom: 6px;
      margin-top: 28px;
      font-size: 18px;
    }}
    h3 {{
      font-size: 16px;
      margin-top: 20px;
    }}
    blockquote {{
      margin: 8px 0 16px 0;
      padding: 8px 12px;
      background: #f8fafc;
      border-left: 3px solid #2563eb;
      color: #475569;
      font-size: 13px;
    }}
    ul {{
      padding-left: 20px;
    }}
    li {{
      margin-bottom: 10px;
    }}
    a {{
      color: #2563eb;
      text-decoration: none;
    }}
    a:hover {{
      text-decoration: underline;
    }}
  </style>
</head>
<body>
  <div class="container">
    <div class="header" style="background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%); background-color: #1e293b; color: #ffffff !important; padding: 28px 32px; text-align: left;">
      <h1 style="color: #ffffff !important; margin: 0 0 6px 0; font-size: 24px; font-weight: 700; letter-spacing: -0.02em;">⚡ News Aggregator Bot</h1>
      <p style="color: #94a3b8 !important; margin: 0; font-size: 14px;">Tages-Briefing für den {current_date}</p>
    </div>
    <div class="content">
      {body_html}
    </div>
  </div>
</body>
</html>
"""
    return html_template


def save_html_preview(html_content: str, output_dir: str = "output") -> str:
    """Speichert eine lokale HTML-Datei zur Vorschau / als lokale Web-Ansicht."""
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    file_path = out_path / "daily_digest.html"
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(html_content)
    print(f"✅ Lokale Vorschau erstellt: {file_path.resolve()}")
    return str(file_path.resolve())


def send_email_via_resend(html_content: str, subject: str = None) -> bool:
    """Sendet die E-Mail über die moderne Resend API."""
    api_key = os.getenv("RESEND_API_KEY")
    email_to = os.getenv("EMAIL_TO")
    email_from = os.getenv("EMAIL_FROM", "News Bot <onboarding@resend.dev>")
    
    if not api_key or api_key.startswith("re_your_"):
        print("[Hinweis] Kein gültiger RESEND_API_KEY vorhanden. E-Mail Versand übersprungen.")
        return False

    if not email_to or "@example.com" in email_to:
        print("[Hinweis] Kein gültiger EMAIL_TO Empfänger eingetragen.")
        return False

    if not subject:
        subject = f"📰 Dein Daily News Digest - {datetime.now().strftime('%d.%m.%Y')}"

    response = requests.post(
        "https://api.resend.com/emails",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "from": email_from,
            "to": [email_to],
            "subject": subject,
            "html": html_content,
        },
    )

    if response.status_code in [200, 201]:
        print(f"🚀 E-Mail erfolgreich via Resend versendet an {email_to}!")
        return True
    else:
        print(f"[Fehler] Resend API Fehler ({response.status_code}): {response.text}")
        return False


def send_email_via_smtp(html_content: str, subject: str = None) -> bool:
    """Sendet die E-Mail per klassischem SMTP."""
    smtp_host = os.getenv("SMTP_HOST")
    smtp_port = int(os.getenv("SMTP_PORT", 587))
    smtp_user = os.getenv("SMTP_USER")
    smtp_pass = os.getenv("SMTP_PASS")
    email_to = os.getenv("EMAIL_TO")

    if not all([smtp_host, smtp_user, smtp_pass, email_to]) or "@example.com" in email_to:
        print("[Hinweis] Unvollständige SMTP-Zugangsdaten in .env.")
        return False

    if not subject:
        subject = f"📰 Dein Daily News Digest - {datetime.now().strftime('%d.%m.%Y')}"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = smtp_user
    msg["To"] = email_to
    msg.attach(MIMEText(html_content, "html"))

    try:
        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.sendmail(smtp_user, email_to, msg.as_string())
        print(f"🚀 E-Mail erfolgreich via SMTP versendet an {email_to}!")
        return True
    except Exception as e:
        print(f"[Fehler] SMTP Versand fehlgeschlagen: {e}")
        return False


def dispatch_digest(markdown_summary: str):
    """Hauptverteiler: Erstellt HTML, speichert Vorschau und sendet Mail (sofern konfiguriert)."""
    html = markdown_to_html_email(markdown_summary)
    
    # 1. Immer lokale HTML-Datei erstellen (kann auch für Web-Hosting genutzt werden)
    save_html_preview(html)

    # 2. E-Mail Versand je nach Konfiguration
    provider = os.getenv("EMAIL_PROVIDER", "resend").lower()
    if provider == "resend":
        send_email_via_resend(html)
    elif provider == "smtp":
        send_email_via_smtp(html)
    else:
        print(f"[Info] Unbekannter EMAIL_PROVIDER '{provider}'. Nur lokale Vorschau gespeichert.")
