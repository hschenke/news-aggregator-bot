import os
import time
import hmac
import hashlib
from pathlib import Path
from typing import Optional

AUTH_SALT = b"news_aggregator_bot_secure_salt_v1"
COOKIE_AUTH_NAME = "news_bot_session"
COOKIE_EXPIRY_DAYS = 365


def get_configured_app_password(config_path: str = "config/sources.yaml") -> str:
    """
    Ermittelt das App-Passwort in folgender Prioritätsreihenfolge:
    1. Umgebungsvariable APP_PASSWORD (.env oder GitHub Actions Secrets)
    2. Streamlit Secrets (st.secrets["APP_PASSWORD"])
    3. sources.yaml (settings.app_password)
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

    try:
        from src.aggregator import load_sources
        config = load_sources(config_path)
        pw = config.get("settings", {}).get("app_password")
        if pw and str(pw).strip():
            return str(pw).strip()
    except Exception:
        pass

    return ""


def generate_persistent_auth_token(password: str) -> str:
    """Erstellt ein sicheres, langlebiges HMAC-Token aus dem Passwort (ohne Klartext im Link)."""
    if not password:
        return ""
    return hmac.new(password.encode("utf-8"), AUTH_SALT, hashlib.sha256).hexdigest()


def generate_timestamped_token(password: str) -> str:
    """Erstellt ein zeitgestempeltes Token (z. B. für kurzlebigere Session-Cookies)."""
    if not password:
        return ""
    timestamp = str(int(time.time()))
    sig = hmac.new(
        password.encode("utf-8"),
        f"{timestamp}:{AUTH_SALT.decode()}".encode("utf-8"),
        hashlib.sha256
    ).hexdigest()
    return f"{timestamp}:{sig}"


def verify_auth_token(token: str, password: str, max_age_days: int = COOKIE_EXPIRY_DAYS) -> bool:
    """
    Verifiziert ein Authentifizierungs-Token gegen das konfigurierte Passwort.
    Akzeptiert:
    1. Persistentes HMAC-Token
    2. Zeitgestempeltes Token (alt oder neu)
    3. Das Passwort selbst im Klartext
    """
    if not token or not password:
        return False

    token = str(token).strip()
    password = str(password).strip()

    # 1. Direkter Passwort-Abgleich
    if hmac.compare_digest(token, password):
        return True

    # 2. Persistentes HMAC-Token
    expected_persistent = generate_persistent_auth_token(password)
    if hmac.compare_digest(token, expected_persistent):
        return True

    # 3. Zeitgestempeltes Token
    if ":" in token:
        try:
            timestamp_str, sig = token.split(":", 1)
            # Neues Format mit Salt
            expected_sig = hmac.new(
                password.encode("utf-8"),
                f"{timestamp_str}:{AUTH_SALT.decode()}".encode("utf-8"),
                hashlib.sha256
            ).hexdigest()
            if hmac.compare_digest(sig, expected_sig):
                ts = int(timestamp_str)
                if (time.time() - ts) <= (86400 * max_age_days):
                    return True
        except Exception:
            pass

        try:
            # Altes Format (Abwärtskompatibilität)
            timestamp_str, sig = token.split(":", 1)
            old_sig = hmac.new(
                password.encode("utf-8"),
                timestamp_str.encode("utf-8"),
                hashlib.sha256
            ).hexdigest()
            if hmac.compare_digest(sig, old_sig):
                ts = int(timestamp_str)
                if (time.time() - ts) <= (86400 * max_age_days):
                    return True
        except Exception:
            pass

    return False
