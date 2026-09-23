"""
Einstiegspunkt für Streamlit Cloud (Alternative zu streamlit_app.py).
Führt die Web-App aus src/webapp.py aus.
"""
import sys
import runpy
from pathlib import Path

root_dir = Path(__file__).resolve().parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

webapp_path = root_dir / "src" / "webapp.py"
runpy.run_path(str(webapp_path), run_name="__main__")
