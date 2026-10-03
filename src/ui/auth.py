"""
Authentication and session management for News Aggregator Bot UI.
Provides dual-role access:
1. Guest / Reader: Can view the 24h articles tab directly (e.g. from daily email digest).
2. Administrator: Full access unlocked via sidebar password login.
"""

from __future__ import annotations

import logging
import streamlit as st

from src.auth import (
    get_configured_app_password,
    verify_admin_token,
    generate_admin_token,
    get_auth_role,
    ROLE_ADMIN,
    ROLE_READONLY,
)
from src.ui.styles import embed_client_script

logger = logging.getLogger(__name__)

ROLE_GUEST = "guest"
COOKIE_AUTH_NAME = "news_bot_session"
COOKIE_ADMIN_NAME = "news_bot_admin_session"
COOKIE_EXPIRY_DAYS = 7

try:
    from streamlit_cookies_controller import CookieController
    cookie_controller = CookieController(key="news_bot_auth_cookie_ctrl")
except Exception:
    cookie_controller = None


def get_current_role() -> str:
    """
    Determines the current user role:
    Returns ROLE_ADMIN if authenticated as admin (or no password configured), otherwise ROLE_GUEST.
    """
    expected_password = get_configured_app_password()
    if not expected_password:
        return ROLE_ADMIN

    # If user explicitly logged out in this session
    if st.session_state.get("logged_out", False):
        return ROLE_GUEST

    # 1. Already in session state
    if st.session_state.get("auth_role") == ROLE_ADMIN:
        return ROLE_ADMIN

    # 2. Check Request Header Cookies (st.context.cookies)
    if hasattr(st, "context") and hasattr(st.context, "cookies"):
        admin_cookie = st.context.cookies.get(COOKIE_ADMIN_NAME)
        if admin_cookie and verify_admin_token(admin_cookie, expected_password):
            st.session_state["authenticated"] = True
            st.session_state["auth_role"] = ROLE_ADMIN
            return ROLE_ADMIN

    # 3. Check CookieController
    if cookie_controller:
        try:
            admin_ctrl = cookie_controller.get(COOKIE_ADMIN_NAME)
            if admin_ctrl and verify_admin_token(admin_ctrl, expected_password):
                st.session_state["authenticated"] = True
                st.session_state["auth_role"] = ROLE_ADMIN
                return ROLE_ADMIN
        except Exception:
            pass

    # 4. Check Query Parameter (?auth=... or ?token=...)
    url_auth = st.query_params.get("auth") or st.query_params.get("token")
    if url_auth:
        role = get_auth_role(url_auth, expected_password)
        if role == ROLE_ADMIN:
            st.session_state["authenticated"] = True
            st.session_state["auth_role"] = ROLE_ADMIN
            return ROLE_ADMIN

    return ROLE_GUEST


def is_admin_user() -> bool:
    """Helper returning True if current session has admin privileges."""
    return get_current_role() == ROLE_ADMIN


def login_admin(password: str) -> bool:
    """Attempts admin login with given password."""
    expected_password = get_configured_app_password()
    if not expected_password or password.strip() == expected_password.strip():
        st.session_state["authenticated"] = True
        st.session_state["auth_role"] = ROLE_ADMIN
        st.session_state["logged_out"] = False

        if expected_password:
            admin_token = generate_admin_token(expected_password)
            st.query_params["auth"] = admin_token
            if cookie_controller:
                try:
                    cookie_controller.set(COOKIE_ADMIN_NAME, admin_token, max_age=86400.0, same_site="lax")
                except Exception:
                    pass
            embed_client_script(f"""
            (function() {{
                try {{
                    localStorage.setItem("{COOKIE_ADMIN_NAME}", "{admin_token}");
                    document.cookie = "{COOKIE_ADMIN_NAME}={admin_token}; path=/; max-age=86400; SameSite=Lax";
                }} catch(e) {{}}
            }})();
            """)
        logger.info("Admin login successful.")
        return True

    logger.warning("Failed admin login attempt.")
    return False


def logout_admin() -> None:
    """Logs out admin and resets session to guest role."""
    st.session_state["authenticated"] = False
    st.session_state["auth_role"] = ROLE_GUEST
    st.session_state["logged_out"] = True

    if "auth" in st.query_params:
        del st.query_params["auth"]
    if "token" in st.query_params:
        del st.query_params["token"]

    if cookie_controller:
        try:
            cookie_controller.remove(COOKIE_AUTH_NAME)
            cookie_controller.remove(COOKIE_ADMIN_NAME)
        except Exception:
            pass

    embed_client_script(f"""
    (function() {{
        try {{
            localStorage.removeItem("{COOKIE_AUTH_NAME}");
            localStorage.removeItem("{COOKIE_ADMIN_NAME}");
            document.cookie = "{COOKIE_AUTH_NAME}=; expires=Thu, 01 Jan 1970 00:00:00 UTC; path=/;";
            document.cookie = "{COOKIE_ADMIN_NAME}=; expires=Thu, 01 Jan 1970 00:00:00 UTC; path=/;";
        }} catch(e) {{}}
    }})();
    """)
    logger.info("Admin logged out.")


def render_sidebar_auth(is_admin: bool) -> None:
    """Renders login/logout controls in the sidebar."""
    expected_password = get_configured_app_password()
    if not expected_password:
        return  # No password configured, always admin

    st.sidebar.markdown("---")
    if is_admin:
        col_adm, col_btn = st.sidebar.columns([3, 2], vertical_alignment="center")
        with col_adm:
            st.caption("👑 **Admin aktiv**")
        with col_btn:
            if st.button("Abmelden", key="btn_sidebar_logout", use_container_width=True):
                logout_admin()
                st.rerun()
    else:
        with st.sidebar.expander("🔐 Admin-Anmeldung", expanded=False):
            st.caption("Admin-Zugang für Einstellungen, Briefing-Generierung und Feeds.")
            pwd_input = st.text_input(
                "Passwort:",
                type="password",
                key="sidebar_pwd_input",
                placeholder="Admin-Passwort...",
            )
            if st.button("Anmelden", key="btn_sidebar_login", type="primary", use_container_width=True):
                if login_admin(pwd_input):
                    st.toast("Erfolgreich als Administrator angemeldet!", icon="🔓")
                    st.rerun()
                else:
                    st.error("Ungültiges Passwort.")
