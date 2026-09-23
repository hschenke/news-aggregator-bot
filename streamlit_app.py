"""
Root Entry Point für Streamlit Community Cloud.
Startet die News-Aggregator Web-App aus src/webapp.py.
"""
import sys
from pathlib import Path

# Sicherstellen, dass das Projekt-Verzeichnis im Suchpfad liegt
root_dir = Path(__file__).resolve().parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

# Web-App ausführen
import src.webapp
