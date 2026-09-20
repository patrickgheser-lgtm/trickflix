"""
TrickFlix - server-ponte locale (porta 8765).

Serve a due cose, perche' l'iframe del player ha origine "opaca" e NON puo'
usare localStorage ne' parlare con Python direttamente:
  - POST /pos    : il player invia il minuto raggiunto (sendBeacon) -> salvato
                   in posizioni.json (cosi' "continua a guardare" riprende davvero).
  - GET  /prefs  : il player invia lingua audio/sottotitoli/qualita' scelte ->
                   preferenze.json (diventano il default per quella serie).
  - GET  /file/<nome> : serve i video scaricati in Download/ (con Range, per il
                   seek) cosi' si possono guardare OFFLINE dentro l'app.
Avviato in un thread da launcher.py. Eseguibile anche da solo per i test.
"""
import os
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, unquote, parse_qs

import storage

BASE = os.path.dirname(os.path.abspath(__file__))
DOWNLOAD_DIR = os.path.join(BASE, "Download")
PORT = 8765


class _Handler(BaseHTTPRequestHandler):
    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        # Private Network Access: l'iframe (origine opaca) deve poter chiamare localhost
        self.send_header("Access-Control-Allow-Private-Network", "true")

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_POST(self):
        path = urlparse(self.path).path
        if path == "/pos":
            try:
                ln = int(self.headers.get("Content-Length", 0) or 0)
                body = self.rfile.read(ln) if ln else b""
                data = json.loads(body.decode("utf-8"))
                if data.get("key"):
                    storage.salva_posizione(data["key"], data.get("p", 0), data.get("d", 0))
            except Exception:
                pass
            self.send_response(204)
            self._cors()
            self.end_headers()
        else:
            self.send_response(404)
            self._cors()
            self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        if path in ("/pos", "/pick", "/prefs", "/vai", "/azione"):
            # "beacon" via GET (immagine): funziona anche dall'iframe a origine opaca
            try:
                q = parse_qs(parsed.query)
                if path == "/pos" and q.get("key", [""])[0]:
                    storage.salva_posizione(q["key"][0], float(q.get("p", [0])[0]), float(q.get("d", [0])[0]))
                elif path == "/pick" and q.get("uid", [""])[0]:
                    storage.salva_pick(q["uid"][0])
                elif path == "/vai" and q.get("ep", [""])[0]:
                    # il popup episodi (o il tasto "prossimo") chiede di cambiare episodio
                    storage.salva_vai(q["ep"][0], q.get("s", [None])[0], q.get("n", [None])[0])
                elif path == "/azione" and q.get("a", [""])[0]:
                    # il player chiede di scaricare o di trasmettere su una TV
                    storage.salva_azione(q["a"][0], q.get("d", [""])[0])
                elif path == "/prefs":
                    # il player ha cambiato lingua/sottotitoli/qualita': diventano il
                    # default per quella serie (e le "ultime usate" per tutto il resto)
                    storage.salva_preferenze(q.get("uid", [""])[0],
                                             audio=q.get("audio", [None])[0],
                                             sub=q.get("sub", [None])[0],
                                             subname=q.get("subname", [None])[0],
                                             qual=q.get("qual", [None])[0])
            except Exception:
                pass
            # risponde un GIF 1x1 trasparente
            gif = (b"GIF89a\x01\x00\x01\x00\x80\x00\x00\xff\xff\xff\x00\x00\x00!\xf9\x04"
                   b"\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;")
            self.send_response(200)
            self._cors()
            self.send_header("Content-Type", "image/gif")
            self.send_header("Content-Length", str(len(gif)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(gif)
        elif path == "/health":
            self.send_response(200)
            self._cors()
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"ok")
        elif path.startswith("/file/"):
            self._serve_file(path[len("/file/"):])
        else:
            self.send_response(404)
            self._cors()
            self.end_headers()

    def _serve_file(self, rel):
        full = os.path.normpath(os.path.join(DOWNLOAD_DIR, rel))
        base = os.path.normpath(DOWNLOAD_DIR)
        if not full.startswith(base) or not os.path.isfile(full):
            self.send_response(404)
            self._cors()
            self.end_headers()
            return
        size = os.path.getsize(full)
        start, end = 0, size - 1
        rng = self.headers.get("Range")
        partial = False
        if rng and rng.startswith("bytes="):
            partial = True
            try:
                s, e = rng[6:].split("-")
                start = int(s) if s else 0
                end = int(e) if e else size - 1
            except Exception:
                start, end = 0, size - 1
        end = min(end, size - 1)
        ext = os.path.splitext(full)[1].lower()
        ctype = {".m3u8": "application/vnd.apple.mpegurl", ".vtt": "text/vtt",
                 ".ts": "video/mp2t", ".mp4": "video/mp4"}.get(ext, "application/octet-stream")
        self.send_response(206 if partial else 200)
        self._cors()
        if partial:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(end - start + 1))
        self.end_headers()
        try:
            with open(full, "rb") as f:
                f.seek(start)
                remaining = end - start + 1
                while remaining > 0:
                    chunk = f.read(min(262144, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)
        except Exception:
            pass

    def log_message(self, *a):
        pass


def avvia(port=PORT):
    """Avvia il ponte in un thread daemon. Ritorna il server (o None se la porta e' occupata)."""
    try:
        srv = ThreadingHTTPServer(("127.0.0.1", port), _Handler)
    except OSError:
        return None
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def url_file(nome):
    """URL del ponte per un file in Download/."""
    from urllib.parse import quote
    return f"http://localhost:{PORT}/file/{quote(nome)}"


if __name__ == "__main__":
    import time
    s = avvia()
    print("bridge attivo su", PORT if s else "(porta occupata)")
    while True:
        time.sleep(3600)
