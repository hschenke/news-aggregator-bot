import os
import time
import hmac
import hashlib
from pathlib import Path
from typing import Optional

AUTH_SALT_READONLY = b"news_bot_readonly_salt_v1"
AUTH_SALT_LEGACY = b"news_aggregator_bot_secure_salt_v1"
COOKIE_AUTH_NAME = "news_bot_session"
COOKIE_EXPIRY_DAYS = 365

ROLE_ADMIN = "admin"
ROLE_READONLY = "readonly"


def get_configured_app_password(config_path: str = "config/sources.yaml") -> str:
    """
    Ermittelt das App-Passwort ausschließlich aus sicheren Secrets:
    1. Umgebungsvariable APP_PASSWORD (.env lokal oder GitHub Actions Secrets)
    2. Streamlit Secrets (st.secrets["APP_PASSWORD"])
    (Wird niemals im Quelltext oder in sources.yaml gespeichert!)
    """
    env_pw = os.getenv("APP_PASSWORD")
    if env_pw and env_pw.strip():
        return env_pw.strip()

    try:
        import streamlit as st
        if hasattr(st, "secrets") and "APP_PASSWORD" in st.secrets:
            pw = str(st.secrets["APP_PASSWORD"]).strip()
            if pw:
                return pw
    except Exception:
        pass

    return ""


def generate_readonly_auth_token(password: str) -> str:
    """
    Erstellt ein sicheres HMAC-Token für reinen LESE-ZUGRIFF.
    Dieses Token wird an die Links im täglichen E-Mail-Briefing angehängt.
    Selbst wenn jemand den Link kopiert oder mitliest, erhält er damit NUR Lesezugriff
    und kann keinerlei Feeds, Quellen oder Einstellungen verändern!
    """
    if not password:
        return ""
    return hmac.new(password.encode("utf-8"), AUTH_SALT_READONLY, hashlib.sha256).hexdigest()


def generate_persistent_auth_token(password: str) -> str:
    """Abwärtskompatible Alias-Funktion für das Readonly-Token."""
    return generate_readonly_auth_token(password)


def get_auth_role(credential: str, password: str) -> Optional[str]:
    """
    Prüft die übergebene Eingabe (Passwort oder Token) und ermittelt die Berechtigung:
    - ROLE_ADMIN ("admin"): Wenn das echte APP_PASSWORD im Klartext eingegeben wurde.
    - ROLE_READONLY ("readonly"): Wenn das signierte HMAC-Token aus der E-Mail übergeben wurde.
    - None: Ungültige Zugangsdaten.
    """
    if not credential or not password:
        return None

    credential = str(credential).strip()
    password = str(password).strip()

    # 1. Echtes Passwort eingegeben -> Volle Administrationsrechte
    if hmac.compare_digest(credential, password):
        return ROLE_ADMIN

    # 2. Signiertes Readonly-Token aus dem E-Mail-Briefing
    expected_readonly = generate_readonly_auth_token(password)
    if hmac.compare_digest(credential, expected_readonly):
        return ROLE_READONLY

    # 3. Vorheriges Salt (Abwärtskompatibilität für bereits versendete E-Mails)
    legacy_token = hmac.new(password.encode("utf-8"), AUTH_SALT_LEGACY, hashlib.sha256).hexdigest()
    if hmac.compare_digest(credential, legacy_token):
        return ROLE_READONLY

    # 4. Zeitgestempeltes Token (falls vorhanden) -> Readonly
    if ":" in credential:
        try:
            timestamp_str, sig = credential.split(":", 1)
            for salt in [AUTH_SALT_READONLY, AUTH_SALT_LEGACY]:
                expected_sig = hmac.new(
                    password.encode("utf-8"),
                    f"{timestamp_str}:{salt.decode()}".encode("utf-8"),
                    hashlib.sha256
                ).hexdigest()
                if hmac.compare_digest(sig, expected_sig):
                    return ROLE_READONLY
        except Exception:
            pass

    return None


def verify_auth_token(token: str, password: str, max_age_days: int = COOKIE_EXPIRY_DAYS) -> bool:
    """Verifiziert, ob ein Token gültig ist (entweder Admin oder Readonly)."""
    return get_auth_role(token, password) is not None

