"""
TrickFlix - apertura finestre Chrome.
- apri_app(url): apre l'app in modalita' "app" (finestra pulita, sembra un programma).
- apri_sorgente(url): apre la pagina sorgente in Chrome (dove vive l'estensione che cattura).
Usano il profilo PREDEFINITO di Chrome (dove l'utente ha caricato l'estensione una volta).
"""
import os
import sys
import shutil
import subprocess
import webbrowser


def trova_chrome():
    if sys.platform.startswith("win"):
        cand = [
            os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"),
                         r"Google\Chrome\Application\chrome.exe"),
            os.path.join(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
                         r"Google\Chrome\Application\chrome.exe"),
            os.path.join(os.environ.get("LOCALAPPDATA", ""),
                         r"Google\Chrome\Application\chrome.exe"),
        ]
    elif sys.platform == "darwin":
        cand = ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"]
    else:
        cand = [shutil.which(n) for n in ("google-chrome", "google-chrome-stable", "chromium")]
    for c in cand:
        if c and os.path.exists(c):
            return c
    return None


def apri_app(url):
    """Finestra Chrome in modalita' app (senza barra indirizzi/tab)."""
    chrome = trova_chrome()
    if chrome:
        try:
            subprocess.Popen([chrome, f"--app={url}", "--no-first-run"])
            return
        except Exception:
            pass
    webbrowser.open(url)


def apri_sorgente(url):
    """Apre la sorgente in una NUOVA FINESTRA Chrome dedicata (stesso profilo dell'estensione).
    Cosi' la cattura e' isolata dalle tue schede e, chiudendo l'unica scheda dopo la cattura,
    si chiude tutta la finestra (non lascia schede orfane nel tuo browser)."""
    chrome = trova_chrome()
    if chrome:
        try:
            subprocess.Popen([chrome, "--new-window", url])
            return
        except Exception:
            pass
    webbrowser.open(url)
