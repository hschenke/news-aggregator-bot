"""
Root Entry Point für Streamlit Community Cloud.
Führt die News-Aggregator Web-App aus src/webapp.py aus.
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

# Sicherstellen, dass das Projekt-Verzeichnis im Suchpfad liegt
root_dir = Path(__file__).resolve().parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

# Cache für interne Projekt-Module bei Streamlit Hot-Reloads leeren,
# damit neu gepushte Code-Änderungen sofort frisch von der Festplatte geladen werden!
for mod_name in list(sys.modules.keys()):
    if mod_name == "src" or mod_name.startswith("src."):
        del sys.modules[mod_name]

webapp_path = root_dir / "src" / "webapp.py"
runpy.run_path(str(webapp_path), run_name="__main__")

