"""
End-to-End Smoke Tests für streamlit_app.py und src/webapp.py unter Verwendung von Streamlits offiziellem AppTest Framework.
Prüft das fehlerfreie Rendern der Webanwendung inklusive Deeplinks und verhindert NameError / Syntaxfehler.
"""

import unittest
from pathlib import Path
from streamlit.testing.v1 import AppTest

APP_PATH = str(Path(__file__).resolve().parent.parent / "streamlit_app.py")


class TestWebappSmoke(unittest.TestCase):

    def test_app_renders_without_exception(self):
        """Prüft, dass die Streamlit App beim Standardaufruf ohne Exception durchläuft."""
        at = AppTest.from_file(APP_PATH, default_timeout=30)
        at.run()
        if at.exception:
            error_msgs = [f"{exc.type}: {exc.value}" for exc in at.exception]
            self.fail(f"Streamlit App warf unerwartete Exceptions: {error_msgs}")

    def test_app_renders_with_deeplinks(self):
        """Prüft, dass Deeplinks (Kategorie + Feed) ohne Exception durchlaufen."""
        at = AppTest.from_file(APP_PATH, default_timeout=30)
        at.query_params["category"] = "Fun"
        at.query_params["feed"] = "Witz des Tages"
        at.run()
        if at.exception:
            error_msgs = [f"{exc.type}: {exc.value}" for exc in at.exception]
            self.fail(f"Streamlit App warf unerwartete Exceptions bei Deeplink: {error_msgs}")


if __name__ == "__main__":
    unittest.main()
