"""
TrickFlix - Avvio applicazione (senza console).
1. Libera le porte da avvii precedenti.
2. Avvia il server Streamlit (log in app_log.txt).
3. Aspetta che risponda e apre l'app in Chrome (finestra "app").
4. Resta in background a tenere vivo il server.
Lanciato con pythonw.exe: nessun terminale visibile. I problemi finiscono in app_log.txt.
"""
import os
import sys
import time
import socket
import hashlib
import subprocess

BASE = os.path.dirname(os.path.abspath(__file__))
PORTA_APP = 8501
PORTA_PONTE = 8765
import percorsi
LOG = percorsi.dato("app_log.txt")

# Evita che i sottoprocessi facciano lampeggiare finestre-console (avvio windowless)
_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform.startswith("win") else 0


def _log(msg):
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(f"[launcher] {msg}\n")
    except Exception:
        pass


def libera_porta(porta):
    """Chiude eventuali processi rimasti su 'porta' (avvii precedenti). Win + Mac/Linux."""
    if sys.platform.startswith("win"):
        try:
            out = subprocess.check_output(
                f'netstat -ano -p tcp | findstr ":{porta} "', shell=True, text=True,
                creationflags=_NO_WINDOW,
            )
        except Exception:
            return
        pids = set()
        for riga in out.splitlines():
            parti = riga.split()
            if len(parti) >= 5 and parti[1].endswith(f":{porta}"):
                pids.add(parti[-1])
        for pid in pids:
            if pid and pid != "0":
                subprocess.run(f"taskkill /F /PID {pid}", shell=True,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               creationflags=_NO_WINDOW)
    else:
        # macOS / Linux: i PID in ascolto sulla porta, via lsof
        try:
            out = subprocess.check_output(["lsof", "-ti", f"tcp:{porta}"], text=True)
        except Exception:
            return
        for pid in out.split():
            try:
                subprocess.run(["kill", "-9", pid],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception:
                pass


def assicura_dipendenze():
    """Installa/aggiorna i pacchetti se requirements.txt e' cambiato dall'ultima volta.
    Serve perche' i launcher (TrickFlix.exe su Windows, TrickFlix.command su Mac) installano
    i requisiti SOLO alla prima installazione: cosi' invece una NUOVA dipendenza aggiunta a
    requirements.txt (es. curl_cffi) arriva anche agli installati gia' esistenti, su entrambe
    le piattaforme, senza doverla installare a mano. Gira ad ogni avvio ma fa pip SOLO quando
    il file e' cambiato (confronto per hash), quindi normalmente e' un no-op istantaneo."""
    req = os.path.join(BASE, "requirements.txt")
    if not os.path.isfile(req):
        return
    try:
        with open(req, "rb") as f:
            firma = hashlib.sha1(f.read()).hexdigest()
    except Exception:
        return
    marker = percorsi.dato(".deps_ok")
    try:
        with open(marker, encoding="utf-8") as f:
            if f.read().strip() == firma:
                return                          # requisiti gia' allineati -> niente da fare
    except Exception:
        pass
    _log("requirements.txt cambiato: installo le dipendenze…")
    py = sys.executable.replace("pythonw.exe", "python.exe")
    try:
        subprocess.run([py, "-m", "pip", "install", "-r", req],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       creationflags=_NO_WINDOW, timeout=600)
        with open(marker, "w", encoding="utf-8") as f:
            f.write(firma)
        _log("dipendenze installate/aggiornate")
    except Exception as e:
        _log(f"installazione dipendenze fallita: {e}")


def attendi_porta(porta, timeout=40):
    scadenza = time.time() + timeout
    while time.time() < scadenza:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1)
            if s.connect_ex(("127.0.0.1", porta)) == 0:
                return True
        time.sleep(0.4)
    return False


def main():
    percorso_app = os.path.join(BASE, "app.py")
    assicura_dipendenze()          # installa le eventuali nuove dipendenze (curl_cffi, ...)
    libera_porta(PORTA_APP)
    libera_porta(PORTA_PONTE)

    # Server-ponte: salva il minuto (continua a guardare) + serve i video offline
    try:
        import bridge
        if bridge.avvia(PORTA_PONTE):
            _log(f"ponte avviato su {PORTA_PONTE}")
        else:
            _log(f"ponte: porta {PORTA_PONTE} occupata")
    except Exception as e:
        _log(f"ponte non avviato: {e}")

    # python.exe (non pythonw) per il server, ma SENZA finestra console
    py = sys.executable.replace("pythonw.exe", "python.exe")
    log_file = open(LOG, "w", encoding="utf-8")
    server = subprocess.Popen(
        [py, "-m", "streamlit", "run", percorso_app,
         "--server.headless=true", f"--server.port={PORTA_APP}"],
        stdout=log_file, stderr=subprocess.STDOUT, creationflags=_NO_WINDOW,
    )

    if not attendi_porta(PORTA_APP):
        _log("il server Streamlit non si e' avviato in tempo.")
        server.terminate()
        return

    url = f"http://localhost:{PORTA_APP}"
    # --no-browser: usato dal riavvio dopo un aggiornamento. La finestra e' gia'
    # aperta e si riconnette da sola, aprirne un'altra darebbe due TrickFlix.
    if "--no-browser" in sys.argv:
        _log("riavvio dopo aggiornamento: non riapro il browser")
    else:
        try:
            from browser import apri_app
            apri_app(url)
        except Exception as e:
            _log(f"apertura Chrome fallita ({e}); apro nel browser predefinito.")
            import webbrowser
            webbrowser.open(url)

    _log("avviato su " + url)
    try:
        server.wait()
    except KeyboardInterrupt:
        server.terminate()


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        _log(f"ERRORE launcher: {e}")
