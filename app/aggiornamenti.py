"""TrickFlix - aggiornamento automatico.

Come funziona
-------------
Da qualche parte in rete c'è un file "aggiornamento.json" (il MANIFESTO) che dice:
qual è l'ultima versione, cosa è cambiato e, per ogni file dell'app, il suo sha256.
All'avvio l'app lo scarica in background (max una volta al giorno, senza rallentare
l'apertura). Se la versione è più alta di quella in versione.py, compare il popup.

Se l'utente accetta: si scaricano SOLO i file il cui sha256 è diverso da quello che
c'è su disco, si verificano uno per uno, si fa il backup di quelli che verranno
sostituiti e solo alla fine si scambiano. Poi si riavvia.

Cosa NON viene mai toccato
--------------------------
venv/, Download/, python-portable/, .chrome_profile/ e i file personali (dati.json,
posizioni.json, preferenze.json, ...). L'aggiornamento riguarda solo il CODICE: la
build resta quella, i tuoi dati restano i tuoi.

Perché più fonti
----------------
Stesso principio dei domini dei siti (vedi streamingcommunity.py): una fonte sola
prima o poi sparisce. Qui si prova raw.githubusercontent e, se non risponde o serve
roba vecchia, il mirror jsDelivr dello stesso repo - che è un host diverso.
"""

import os
import re
import sys
import json
import time
import shutil
import hashlib
import tempfile
import threading
import subprocess

BASE = os.path.dirname(os.path.abspath(__file__))     # .../app
RADICE = os.path.dirname(BASE)                        # cartella del progetto

REPO = "patrickgheser-lgtm/trickflix"
RAMO = "main"

# Le fonti si provano in ordine. raw.githubusercontent ha una cache breve (~5 min),
# jsDelivr è più lento ad aggiornarsi ma è un host completamente diverso: se GitHub
# diventa irraggiungibile (o il repo sparisce) resta comunque una strada.
FONTI = [
    "https://raw.githubusercontent.com/{repo}/{ramo}/",
    "https://cdn.jsdelivr.net/gh/{repo}@{ramo}/",
]

MANIFESTO = "aggiornamento.json"
import percorsi
CACHE = percorsi.dato("aggiornamento_cache.json")
BACKUP = percorsi.dato(".backup")
OGNI = 24 * 3600          # frequenza del controllo automatico
TIMEOUT = 20

# ─────────────────────────────────────────────────────────────────────────
#  Sicurezza dei percorsi
#  Un aggiornamento scarica ed esegue codice: il manifesto va trattato come
#  dato NON fidato. Questi filtri fanno sì che, qualunque cosa ci sia scritto
#  dentro, non si possa uscire dalla cartella del progetto né sovrascrivere
#  i dati dell'utente.
# ─────────────────────────────────────────────────────────────────────────
_EST_OK = {".py", ".html", ".css", ".js", ".md", ".txt", ".toml", ".ps1",
           ".bat", ".command", ".ico", ".icns"}
_RADICE_OK = {"TrickFlix.bat", "TrickFlix.command", "crea_app_macos.command"}
_CARTELLE_NO = {"venv", "Download", "python-portable", ".chrome_profile",
                "__pycache__", ".backup", "TrickFlix.app", ".git"}
_FILE_NO = {"dati.json", "posizioni.json", "preferenze.json", "vai.json",
            "azione.json", "libreria.json", ".deps_ok", "app_log.txt",
            "aggiornamento_cache.json", "durate_cache.json"}
_PEZZO = re.compile(r"^[A-Za-z0-9._ +-]+$")


def _sicuro(percorso):
    """True se 'percorso' (relativo, con /) può essere scritto dall'aggiornamento."""
    if not percorso or percorso != percorso.strip():
        return False
    if "\\" in percorso or percorso.startswith("/") or ":" in percorso:
        return False
    pezzi = percorso.split("/")
    if any(not _PEZZO.match(p) or p in (".", "..") for p in pezzi):
        return False
    if any(p in _CARTELLE_NO for p in pezzi):
        return False
    if pezzi[-1] in _FILE_NO:
        return False
    if os.path.splitext(pezzi[-1])[1].lower() not in _EST_OK:
        return False
    # o sta dentro app/, oppure è uno dei pochi avviatori in radice
    return pezzi[0] == "app" or (len(pezzi) == 1 and pezzi[0] in _RADICE_OK)


def _sha256(percorso_assoluto):
    try:
        h = hashlib.sha256()
        with open(percorso_assoluto, "rb") as f:
            for blocco in iter(lambda: f.read(131072), b""):
                h.update(blocco)
        return h.hexdigest()
    except Exception:
        return ""


# ─────────────────────────────────────────────────────────────────────────
#  Rete
# ─────────────────────────────────────────────────────────────────────────
def _urls(relativo, cache_buster=False):
    for schema in FONTI:
        url = schema.format(repo=REPO, ramo=RAMO) + relativo
        if cache_buster:
            url += "?t=%d" % int(time.time())
        yield url


def _get(url):
    """Una singola richiesta. Non solleva mai: restituisce bytes o None."""
    import requests
    try:
        r = requests.get(url, timeout=TIMEOUT)
        if r.status_code == 200 and r.content:
            return r.content
    except Exception:
        pass
    return None


def _scarica(relativo, cache_buster=False):
    """Prima fonte che risponde."""
    for url in _urls(relativo, cache_buster):
        dati = _get(url)
        if dati:
            return dati
    return None


def _scarica_verificato(relativo, atteso):
    """Come _scarica, ma accetta il contenuto solo se lo sha256 corrisponde.
    Se una fonte serve una copia vecchia (cache) l'hash non torna e si passa a
    quella dopo: la verifica fa anche da rilevatore di roba stantia."""
    for url in _urls(relativo):
        dati = _get(url)
        if dati is not None and hashlib.sha256(dati).hexdigest() == atteso:
            return dati
    return None


# ─────────────────────────────────────────────────────────────────────────
#  Versioni
# ─────────────────────────────────────────────────────────────────────────
def versione_locale():
    try:
        import versione
        return str(versione.VERSIONE).strip()
    except Exception:
        return "0.0.0"


def _tupla(v):
    """'3.10.0' -> (3, 10, 0). I pezzi non numerici valgono 0, così una versione
    scritta male non manda in eccezione il confronto."""
    fuori = []
    for pezzo in str(v).split("."):
        cifre = "".join(c for c in pezzo if c.isdigit())
        fuori.append(int(cifre) if cifre else 0)
    return tuple(fuori + [0] * (4 - len(fuori)))[:4]


def _piu_recente(a, b):
    return _tupla(a) > _tupla(b)


# ─────────────────────────────────────────────────────────────────────────
#  Controllo (in background)
# ─────────────────────────────────────────────────────────────────────────
_stato = {"manifesto": None, "controllato": 0, "in_corso": False}
_lock = threading.Lock()


def _leggi_cache():
    try:
        with open(CACHE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _scrivi_cache(d):
    try:
        with open(CACHE, "w", encoding="utf-8") as f:
            json.dump(d, f)
    except Exception:
        pass


def _valido(m):
    """Un manifesto accettabile: versione + dizionario di file con sha256 plausibili."""
    if not isinstance(m, dict) or not m.get("versione"):
        return False
    file = m.get("file")
    if not isinstance(file, dict) or not file:
        return False
    for percorso, info in file.items():
        if not _sicuro(percorso):
            return False
        if not isinstance(info, dict):
            return False
        sha = info.get("sha256", "")
        if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{64}", sha):
            return False
    return True


def controlla(forza=False):
    """Scarica il manifesto e lo tiene da parte. Non solleva mai: se la rete non
    c'è, semplicemente non succede niente."""
    with _lock:
        if _stato["in_corso"]:
            return _stato["manifesto"]
        _stato["in_corso"] = True
    try:
        cache = _leggi_cache()
        if not forza and time.time() - cache.get("ts", 0) < OGNI:
            m = cache.get("manifesto")
            if _valido(m):
                _stato["manifesto"] = m
                return m
            return None
        dati = _scarica(MANIFESTO, cache_buster=True)
        if not dati:
            return None
        try:
            m = json.loads(dati.decode("utf-8"))
        except Exception:
            return None
        if not _valido(m):
            return None
        _stato["manifesto"] = m
        _stato["controllato"] = time.time()
        _scrivi_cache({"ts": time.time(), "manifesto": m})
        return m
    finally:
        _stato["in_corso"] = False


def controlla_in_background():
    """Da chiamare all'avvio: non blocca nulla."""
    if _stato["manifesto"] is not None or _stato["in_corso"]:
        return
    threading.Thread(target=controlla, daemon=True).start()


def disponibile():
    """Il manifesto noto, se annuncia una versione più recente di quella installata.
    Altrimenti None."""
    m = _stato["manifesto"]
    if not m:
        return None
    return m if _piu_recente(m.get("versione", "0"), versione_locale()) else None


# ─────────────────────────────────────────────────────────────────────────
#  Applicazione
# ─────────────────────────────────────────────────────────────────────────
def da_aggiornare(manifesto):
    """I file del manifesto che su disco mancano o sono diversi."""
    fuori = []
    for percorso, info in manifesto.get("file", {}).items():
        if not _sicuro(percorso):
            continue
        locale = os.path.join(RADICE, percorso.replace("/", os.sep))
        if _sha256(locale) != info["sha256"]:
            fuori.append((percorso, info["sha256"]))
    return fuori


def applica(manifesto, progresso=None):
    """Scarica e installa. Restituisce (ok, messaggio).

    Tutto o niente: prima si scarica e si verifica OGNI file in una cartella
    temporanea; solo se sono arrivati tutti interi si tocca l'installazione.
    Se lo scambio fallisce a metà, si rimette a posto dal backup.
    """
    lista = da_aggiornare(manifesto)
    if not lista:
        return True, "Era già tutto aggiornato."

    tmp = tempfile.mkdtemp(prefix="tf_agg_")
    try:
        # 1) scarica e verifica TUTTO prima di toccare l'installazione
        for i, (percorso, sha) in enumerate(lista):
            if progresso:
                progresso(i / float(len(lista)), "Scarico %s" % percorso)
            dati = _scarica_verificato(percorso, sha)
            if dati is None:
                return False, ("Download fallito o file corrotto: %s\n"
                               "Non è stato modificato niente." % percorso)
            dest = os.path.join(tmp, percorso.replace("/", os.sep))
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with open(dest, "wb") as f:
                f.write(dati)
            # Ricontrollo il file SCRITTO, non i byte appena ricevuti: la verifica
            # del download sta in _scarica_verificato, ma di quello che finisce
            # nell'installazione deve rispondere chi la tocca. Becca anche una
            # scrittura incompleta o un disco pieno.
            if _sha256(dest) != sha:
                return False, ("Il file scaricato non corrisponde: %s\n"
                               "Non è stato modificato niente." % percorso)

        # 2) backup di quello che sta per essere sostituito
        if progresso:
            progresso(0.9, "Salvo una copia della versione attuale…")
        cartella_backup = os.path.join(BACKUP, versione_locale())
        salvati = []
        for percorso, _ in lista:
            vecchio = os.path.join(RADICE, percorso.replace("/", os.sep))
            if os.path.isfile(vecchio):
                copia = os.path.join(cartella_backup, percorso.replace("/", os.sep))
                os.makedirs(os.path.dirname(copia), exist_ok=True)
                shutil.copy2(vecchio, copia)
                salvati.append((percorso, copia))

        # 3) scambio
        if progresso:
            progresso(0.95, "Installo i file nuovi…")
        fatti = []
        try:
            for percorso, _ in lista:
                sorgente = os.path.join(tmp, percorso.replace("/", os.sep))
                dest = os.path.join(RADICE, percorso.replace("/", os.sep))
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                os.replace(sorgente, dest)
                fatti.append(percorso)
        except Exception as e:
            for percorso, copia in salvati:
                if percorso in fatti:
                    try:
                        shutil.copy2(copia, os.path.join(RADICE, percorso.replace("/", os.sep)))
                    except Exception:
                        pass
            return False, "Installazione interrotta (%s). Ho rimesso la versione precedente." % e

        # 4) se le dipendenze sono cambiate, il launcher le reinstalla al riavvio
        #    (assicura_dipendenze() confronta lo sha1 di requirements.txt con .deps_ok)
        if any(p.endswith("requirements.txt") for p, _ in lista):
            try:
                os.remove(percorsi.dato(".deps_ok"))
            except Exception:
                pass

        _scrivi_cache({})        # il prossimo avvio ricontrolla da zero
        if progresso:
            progresso(1.0, "Fatto.")
        return True, "Aggiornato alla versione %s (%d file)." % (
            manifesto.get("versione", "?"), len(lista))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def riavvia():
    """Rilancia launcher.py e lascia morire questa istanza.

    Non serve uccidere niente a mano: launcher.py all'avvio fa libera_porta() su
    8501 e 8765, quindi è il processo NUOVO a spegnere quello vecchio. Il browser
    già aperto si riconnette da solo, perciò si parte con --no-browser per non
    ritrovarsi due finestre.
    """
    py = sys.executable
    if sys.platform.startswith("win"):
        pythonw = py.replace("python.exe", "pythonw.exe")
        if os.path.isfile(pythonw):
            py = pythonw
        flag = {"creationflags": subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP}
    else:
        flag = {"start_new_session": True}
    subprocess.Popen([py, os.path.join(BASE, "launcher.py"), "--no-browser"],
                     cwd=BASE, stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **flag)
