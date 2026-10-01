"""
Einstiegspunkt für Streamlit Cloud (Alternative zu streamlit_app.py).
Führt die Web-App aus src/webapp.py aus.
"""
import sys
import logging
import runpy
from pathlib import Path

# Sicherstellen, dass UTF-8 und Line-Buffering in Streamlit Cloud aktiv sind
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", line_buffering=True)

# Konfiguriere Streamlit Konsole Logging (Manage App) auf INFO
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stdout,
    force=True,
)

root_dir = Path(__file__).resolve().parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

webapp_path = root_dir / "src" / "webapp.py"
runpy.run_path(str(webapp_path), run_name="__main__")
