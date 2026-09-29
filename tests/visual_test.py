"""
Automatisierter Optik-Test (Visual UI Test) über Chrome DevTools Protocol (CDP).
Startet Headless Chrome, öffnet Desktop- und Mobile-Viewports und erstellt
Screenshots, um das Layout visuell zu verifizieren.
"""

import asyncio
import json
import base64
import subprocess
import time
import sys
import urllib.request
import urllib.parse
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


CHROME_PATH = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
if not Path(CHROME_PATH).exists():
    CHROME_PATH = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"


def start_headless_browser(port: int = 9222) -> subprocess.Popen:
    temp_dir = Path(r"C:\Users\holge\AppData\Local\Temp\optik_test_profile")
    temp_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        CHROME_PATH,
        "--headless=new",
        f"--remote-debugging-port={port}",
        f"--user-data-dir={temp_dir}",
        "--disable-gpu",
        "--no-first-run",
        "--no-default-browser-check",
    ]
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    # Warten, bis der Debug-Port erreichbar ist
    for _ in range(30):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=0.5) as r:
                if r.status == 200:
                    break
        except Exception:
            time.sleep(0.2)
    return proc


async def capture_screen(url: str, out_path: str, width: int = 1280, height: int = 850, port: int = 9222, delay_sec: float = 3.5) -> None:
    # Neuen Tab öffnen
    escaped_url = urllib.parse.quote(url, safe=":/=&?")
    request_obj = urllib.request.Request(f"http://127.0.0.1:{port}/json/new?{escaped_url}", method="PUT")
    with urllib.request.urlopen(request_obj) as resp:
        tab = json.loads(resp.read().decode())
    ws_url = tab["webSocketDebuggerUrl"]
    tab_id = tab["id"]

    try:
        import websockets
        async with websockets.connect(ws_url) as ws:
            is_mobile = width < 768
            # Device Emulation konfigurieren
            await ws.send(json.dumps({
                "id": 1,
                "method": "Emulation.setDeviceMetricsOverride",
                "params": {
                    "width": width,
                    "height": height,
                    "deviceScaleFactor": 2 if is_mobile else 1,
                    "mobile": is_mobile,
                }
            }))
            await ws.recv()

            # Warten bis Streamlit fertig geladen hat (kein Spinner mehr und Expander da)
            for _ in range(40):
                await ws.send(json.dumps({
                    "id": 10,
                    "method": "Runtime.evaluate",
                    "params": {"expression": "Boolean(document.querySelector('[data-testid=\"stExpander\"]') && !document.querySelector('.stSpinner'))"}
                }))
                raw_eval = await ws.recv()
                try:
                    eval_res = json.loads(raw_eval)
                    if eval_res.get("result", {}).get("result", {}).get("value") is True:
                        break
                except Exception:
                    pass
                await asyncio.sleep(0.5)

            # Auf Mobile / Tablet / Landscape: Sidebar ausblenden, um das Hauptlayout zu prüfen
            if width <= 1024:
                await ws.send(json.dumps({
                    "id": 11,
                    "method": "Runtime.evaluate",
                    "params": {"expression": """
                        (function() {
                            var sb = document.querySelector('section[data-testid="stSidebar"]');
                            if (sb) {
                                sb.style.display = 'none';
                                var collapsedBtn = document.querySelector('[data-testid="stSidebarCollapsedControl"]');
                                if (collapsedBtn) collapsedBtn.style.display = 'none';
                                return 'hidden';
                            }
                            return 'no_sb';
                        })()
                    """}
                }))
                eval_res = await ws.recv()
                print("Sidebar-Close Status:", json.loads(eval_res).get("result", {}).get("result", {}).get("value"))
                await asyncio.sleep(0.5)

            # Sicherstellen, dass der Expander 'Filter & Suche' aufgeklappt ist
            await ws.send(json.dumps({
                "id": 12,
                "method": "Runtime.evaluate",
                "params": {"expression": """
                    (function() {
                        var expanders = document.querySelectorAll('[data-testid="stExpander"]');
                        for (var exp of expanders) {
                            if (exp.innerText && exp.innerText.includes("Filter & Suche")) {
                                var details = exp.querySelector('details');
                                if (details && !details.open) {
                                    var summary = details.querySelector('summary');
                                    if (summary) summary.click();
                                }
                            }
                        }
                    })()
                """}
            }))
            await ws.recv()
            await asyncio.sleep(2.0)

            # Suchzeile zentrieren für den Screenshot
            await ws.send(json.dumps({
                "id": 14,
                "method": "Runtime.evaluate",
                "params": {"expression": """
                    (function() {
                        var s = document.querySelector('[data-testid="stHorizontalBlock"]:has(.st-key-input_search_query)');
                        if (s) s.scrollIntoView({block: 'center', behavior: 'instant'});
                    })()
                """}
            }))
            await ws.recv()
            await asyncio.sleep(0.5)

            # Screenshot anfordern
            await ws.send(json.dumps({
                "id": 2,
                "method": "Page.captureScreenshot",
                "params": {"format": "png"}
            }))
            raw_res = await ws.recv()
            res = json.loads(raw_res)
            img_b64 = res["result"]["data"]
            Path(out_path).parent.mkdir(parents=True, exist_ok=True)
            Path(out_path).write_bytes(base64.b64decode(img_b64))
            print(f"Screenshot gespeichert: {out_path} ({width}x{height})")
    finally:
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/json/close/{tab_id}")
        except Exception:
            pass


async def main():
    import urllib.parse
    from dotenv import load_dotenv
    load_dotenv()
    from src.auth import get_configured_app_password, generate_admin_auth_token
    pw = get_configured_app_password()
    token = generate_admin_auth_token(pw) if pw else ""
    auth_query = f"?auth={token}" if token else ""
    base_url = f"http://localhost:8503/{auth_query}"
    print(f"Starte Headless-Browser für {base_url[:35]}...")
    browser_proc = start_headless_browser(9222)
    try:
        print("Erstelle Screenshots für Desktop und Mobile...")
        await capture_screen(base_url, "tests/preview_desktop.png", width=1280, height=950)
        await capture_screen(base_url, "tests/preview_mobile_portrait.png", width=375, height=812)
        await capture_screen(base_url, "tests/preview_mobile_landscape.png", width=812, height=650)
        print("Alle Screenshots erfolgreich erstellt!")
    finally:
        browser_proc.terminate()
        try:
            browser_proc.wait(timeout=2)
        except Exception:
            browser_proc.kill()


if __name__ == "__main__":
    asyncio.run(main())
