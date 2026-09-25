"""
Root Entry Point für Streamlit Community Cloud.
Führt die News-Aggregator Web-App aus src/webapp.py aus.
"""
import sys
import runpy
from pathlib import Path

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

