import os
import sys
import re
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


def _simple_markdown_fallback(md_text: str) -> str:
    """Robuster Fallback zur Konvertierung von Markdown in HTML, falls das markdown-Paket fehlt."""
    lines = md_text.splitlines()
    html_lines = []
    in_list = False
    in_quote = False
    quote_lines = []

    def close_list():
        nonlocal in_list
        if in_list:
            html_lines.append("</ul>")
            in_list = False

    def close_quote():
        nonlocal in_quote, quote_lines
        if in_quote:
            content = " ".join(quote_lines)
            content = _format_inline(content)
            html_lines.append(f"<blockquote><p>{content}</p></blockquote>")
            quote_lines = []
            in_quote = False

    def _format_inline(text: str) -> str:
        text = re.sub(r"\*\*(.*?)\*\*", r"<strong>\1</strong>", text)
        text = re.sub(r"\[(.*?)\]\((.*?)\)", r'<a href="\2">\1</a>', text)
        return text

    for line in lines:
        stripped = line.strip()
        if not stripped:
            close_list()
            close_quote()
            continue

        if stripped.startswith("## "):
            close_list()
            close_quote()
            title = _format_inline(stripped[3:].strip())
            html_lines.append(f"<h2>{title}</h2>")
            continue

        if stripped.startswith("### "):
            close_list()
            close_quote()
            title = _format_inline(stripped[4:].strip())
            html_lines.append(f"<h3>{title}</h3>")
            continue

        if stripped.startswith(">"):
            close_list()
            in_quote = True
            quote_lines.append(stripped.lstrip("> ").strip())
            continue

        if stripped.startswith("- ") or stripped.startswith("* "):
            close_quote()
            if not in_list:
                html_lines.append("<ul>")
                in_list = True
            item_text = _format_inline(stripped[2:].strip())
            html_lines.append(f"<li>{item_text}</li>")
            continue

        close_list()
        close_quote()
        html_lines.append(f"<p>{_format_inline(stripped)}</p>")

    close_list()
    close_quote()
    return "\n".join(html_lines)


def inline_email_styles(html: str) -> str:
    """
    Wendet Inline-Styles auf HTML-Elemente an für maximale E-Mail-Client-Kompatibilität.
    Verhindert, dass Mail-Clients wie Gmail oder Outlook die Stile im <head> verwerfen.
    """
    font_stack = "'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif"

    # 1. Blockquote styling (Callout-Box)
    def style_blockquote(match):
        bq_inner = match.group(1)
        # Style <p> innerhalb von Blockquote
        bq_inner = re.sub(
            r"<p(\s[^>]*)?>",
            rf'<p style="margin: 0; padding: 0; color: #475569; font-size: 13.5px; line-height: 1.5; font-family: {font_stack};">',
            bq_inner,
        )
        # Style <a> innerhalb von Blockquote
        bq_inner = re.sub(
            r'<a\s+([^>]*?)href="([^"]+)"([^>]*)>',
            rf'<a \1href="\2"\3 target="_blank" style="color: #2563eb; font-weight: 600; text-decoration: none; font-family: {font_stack};">',
            bq_inner,
        )
        return (
            rf'<blockquote style="margin: 12px 0 20px 0; padding: 10px 16px; background-color: #f8fafc; '
            rf'border: 1px solid #e2e8f0; border-left: 4px solid #3b82f6; border-radius: 8px; '
            rf'color: #475569; font-size: 13.5px; line-height: 1.5; font-family: {font_stack};">'
            + bq_inner
            + "</blockquote>"
        )

    html = re.sub(r"<blockquote>(.*?)</blockquote>", style_blockquote, html, flags=re.DOTALL)

    # 2. h2 styling
    first_h2 = True
    def style_h2(match):
        nonlocal first_h2
        m_top = "8px" if first_h2 else "32px"
        first_h2 = False
        attrs = match.group(1) or ""
        content = match.group(2)
        return (
            f'<h2{attrs} style="font-family: {font_stack}; '
            f'color: #0f172a; font-size: 20px; font-weight: 700; letter-spacing: -0.02em; '
            f'border-bottom: 2px solid #f1f5f9; padding-bottom: 8px; margin-top: {m_top}; margin-bottom: 14px;">{content}</h2>'
        )
    html = re.sub(r"<h2(\s[^>]*)?>(.*?)</h2>", style_h2, html)

    # 3. h3 styling
    html = re.sub(
        r"<h3(\s[^>]*)?>(.*?)</h3>",
        rf'<h3\1 style="font-family: {font_stack}; color: #0f172a; font-size: 16px; font-weight: 600; margin-top: 20px; margin-bottom: 10px;">\2</h3>',
        html,
    )

    # 4. ul styling
    html = re.sub(
        r"<ul(\s[^>]*)?>",
        rf'<ul\1 style="padding-left: 20px; margin: 14px 0 24px 0; list-style-type: disc; font-family: {font_stack};">',
        html,
    )

    # 5. li styling
    html = re.sub(
        r"<li(\s[^>]*)?>",
        rf'<li\1 style="margin-bottom: 12px; font-size: 14.5px; line-height: 1.6; color: #334155; font-family: {font_stack};">',
        html,
    )

    # 6. strong styling
    html = re.sub(
        r"<strong(\s[^>]*)?>(.*?)</strong>",
        r'<strong\1 style="color: #0f172a; font-weight: 600;">\2</strong>',
        html,
    )

    # 7. Verbleibende <a>-Tags (z. B. in Listen)
    def style_a(match):
        full_tag = match.group(0)
        if 'style="' in full_tag:
            return full_tag
        return re.sub(
            r'<a\s+([^>]*?)href="([^"]+)"([^>]*)>',
            rf'<a \1href="\2"\3 target="_blank" style="color: #2563eb; text-decoration: none; font-weight: 600; font-family: {font_stack};">',
            full_tag,
        )
    html = re.sub(r'<a\s+[^>]*>.*?</a>', style_a, html, flags=re.DOTALL)

    # 8. Verbleibende <p>-Tags (außerhalb von Blockquotes)
    def style_p(match):
        full_tag = match.group(0)
        if 'style="' in full_tag:
            return full_tag
        return rf'<p style="margin: 0 0 12px 0; line-height: 1.6; font-size: 14.5px; color: #334155; font-family: {font_stack};">'
    html = re.sub(r"<p(\s[^>]*)?>", style_p, html)

    return html


def markdown_to_html_email(markdown_content: str) -> str:
    """Wandelt einfaches Markdown in ein sauberes, responsives HTML-Email-Template mit Inline-Styles um."""
    try:
        import markdown
        raw_body_html = markdown.markdown(markdown_content, extensions=["extra", "tables"])
    except ImportError:
        raw_body_html = _simple_markdown_fallback(markdown_content)

    body_html = inline_email_styles(raw_body_html)
    current_date = datetime.now().strftime("%d.%m.%Y")

    html_template = f"""<!DOCTYPE html>
<html lang="de" xmlns="http://www.w3.org/1999/xhtml" xmlns:v="urn:schemas-microsoft-com:vml" xmlns:o="urn:schemas-microsoft-com:office:office">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta http-equiv="X-UA-Compatible" content="IE=edge">
  <meta name="x-apple-disable-message-reformatting">
  <title>Dein Daily News Digest</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700&display=swap" rel="stylesheet">
  <!--[if mso]>
  <style>
    * {{ font-family: sans-serif !important; }}
  </style>
  <![endif]-->
  <style>
    @import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700&display=swap');

    body {{
      font-family: 'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
      line-height: 1.65;
      color: #1e293b;
      background-color: #f1f5f9;
      margin: 0;
      padding: 28px 12px;
      -webkit-font-smoothing: antialiased;
      -moz-osx-font-smoothing: grayscale;
    }}
    .container {{
      max-width: 680px;
      margin: 0 auto;
      background: #ffffff;
      border-radius: 16px;
      overflow: hidden;
      box-shadow: 0 10px 25px -5px rgba(15, 23, 42, 0.08), 0 8px 10px -6px rgba(15, 23, 42, 0.04);
      border: 1px solid #e2e8f0;
    }}
    .header {{
      background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%);
      background-color: #0f172a;
      color: #ffffff !important;
      padding: 32px 36px;
      text-align: left;
    }}
    .header h1 {{
      font-family: 'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
      margin: 0 0 6px 0;
      font-size: 24px;
      font-weight: 700;
      letter-spacing: -0.025em;
      color: #ffffff !important;
    }}
    .header p {{
      font-family: 'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
      margin: 0;
      color: #94a3b8 !important;
      font-size: 14px;
      font-weight: 500;
    }}
    .content {{
      padding: 36px;
    }}
    .content h1, .content h2, .content h3 {{
      font-family: 'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
      color: #0f172a;
      letter-spacing: -0.02em;
    }}
    h2 {{
      border-bottom: 2px solid #f1f5f9;
      padding-bottom: 8px;
      margin-top: 32px;
      font-size: 20px;
      font-weight: 700;
    }}
    h3 {{
      font-size: 16px;
      font-weight: 600;
      margin-top: 20px;
    }}
    blockquote {{
      margin: 12px 0 18px 0;
      padding: 10px 16px;
      background: #f8fafc;
      border: 1px solid #e2e8f0;
      border-left: 4px solid #3b82f6;
      border-radius: 8px;
      color: #475569;
      font-size: 13.5px;
      line-height: 1.5;
    }}
    blockquote a {{
      color: #2563eb;
      font-weight: 600;
      text-decoration: none;
    }}
    blockquote a:hover {{
      text-decoration: underline;
    }}
    ul {{
      padding-left: 20px;
      margin: 14px 0;
    }}
    li {{
      margin-bottom: 12px;
      font-size: 14.5px;
      line-height: 1.6;
      color: #334155;
    }}
    li strong {{
      color: #0f172a;
      font-weight: 600;
    }}
    a {{
      color: #2563eb;
      text-decoration: none;
      font-weight: 600;
    }}
    a:hover {{
      color: #1d4ed8;
      text-decoration: underline;
    }}
    @media only screen and (max-width: 600px) {{
      body {{
        padding: 12px 6px !important;
      }}
      .outer-td {{
        padding: 12px 6px !important;
      }}
      .container {{
        border-radius: 12px !important;
      }}
      .header {{
        padding: 24px 20px !important;
        border-top-left-radius: 12px !important;
        border-top-right-radius: 12px !important;
      }}
      .content {{
        padding: 24px 18px 32px 18px !important;
      }}
      .header h1 {{
        font-size: 20px !important;
      }}
    }}
  </style>
</head>
<body style="font-family: 'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; line-height: 1.65; color: #1e293b; background-color: #f1f5f9; margin: 0; padding: 28px 12px; -webkit-font-smoothing: antialiased;">
  <table role="presentation" width="100%" border="0" cellspacing="0" cellpadding="0" style="background-color: #f1f5f9; width: 100% !important; margin: 0; padding: 0;">
    <tr>
      <td class="outer-td" align="center" valign="top" style="padding: 28px 12px;">
        <!--[if (gte mso 9)|(IE)]>
        <table role="presentation" width="680" border="0" cellspacing="0" cellpadding="0" align="center">
          <tr>
            <td width="680">
        <![endif]-->
        <div class="container" style="max-width: 680px; width: 100%; margin: 0 auto; background-color: #ffffff; border-radius: 16px; overflow: hidden; box-shadow: 0 10px 25px -5px rgba(15, 23, 42, 0.08), 0 8px 10px -6px rgba(15, 23, 42, 0.04); border: 1px solid #e2e8f0; text-align: left;">
          <div class="header" style="background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%); background-color: #0f172a; color: #ffffff !important; padding: 32px 36px; text-align: left; border-top-left-radius: 16px; border-top-right-radius: 16px;">
            <h1 style="font-family: 'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; color: #ffffff !important; margin: 0 0 6px 0; font-size: 24px; font-weight: 700; letter-spacing: -0.025em; line-height: 1.25;">⚡ News Aggregator Bot</h1>
            <p style="font-family: 'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; color: #94a3b8 !important; margin: 0; font-size: 14px; font-weight: 500;">Tages-Briefing für den {current_date}</p>
          </div>
          <div class="content" style="padding: 36px 36px 44px 36px; background-color: #ffffff; border-bottom-left-radius: 16px; border-bottom-right-radius: 16px;">
            {body_html}
          </div>
        </div>
        <!--[if (gte mso 9)|(IE)]>
            </td>
          </tr>
        </table>
        <![endif]-->
      </td>
    </tr>
  </table>
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
