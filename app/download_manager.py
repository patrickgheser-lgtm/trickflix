"""
TrickFlix - gestore dei download in background + libreria dei file scaricati.

I download girano in un thread (non bloccano l'app): stato/avanzamento/velocita'
sono in un registro globale che la home rilegge ad ogni refresh. Si possono
annullare. Ogni titolo scaricato e' un PACCHETTO HLS LOCALE in una sua cartella
dentro Download/ (vedi downloader.py): si riguarda offline con hls.js (tracce
audio/sottotitoli selezionabili) o si elimina.
"""
import os
import re
import json
import time
import uuid
import queue
import shutil
import subprocess
import threading

import downloader as dl

_DIR = os.path.dirname(os.path.abspath(__file__))
DOWNLOAD_DIR = os.path.join(_DIR, "Download")
LIB = os.path.join(DOWNLOAD_DIR, "libreria.json")

_jobs = {}
_lock = threading.Lock()


# ---------- libreria ----------
def leggi_libreria():
    try:
        with open(LIB, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _salva_libreria(d):
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    tmp = LIB + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    os.replace(tmp, LIB)


def _registra(meta, file_rel, titolo):
    lib = leggi_libreria()
    uid = meta["uid"]
    voce = lib.get(uid) or {"name": meta.get("name"), "type": meta.get("type"),
                            "poster": meta.get("poster"), "landscape": meta.get("landscape"),
                            "anilist_id": meta.get("anilist_id"), "provider": meta.get("provider"),
                            "id": meta.get("id"), "slug": meta.get("slug"), "episodi": []}
    voce["poster"] = voce.get("poster") or meta.get("poster")
    voce["landscape"] = voce.get("landscape") or meta.get("landscape")
    voce["anilist_id"] = voce.get("anilist_id") or meta.get("anilist_id")
    voce["episodi"] = [e for e in voce["episodi"] if e.get("file") != file_rel]
    voce["episodi"].append({"label": meta.get("ep_label") or titolo, "file": file_rel,
                            "resume_key": meta.get("resume_key"), "titolo": titolo,
                            "ep_id": meta.get("ep_id"), "season": meta.get("season"),
                            "number": meta.get("number"), "ts": time.time()})
    voce["episodi"].sort(key=lambda e: (e.get("season") or 0, _num(e.get("number")), e.get("ts", 0)))
    lib[uid] = voce
    _salva_libreria(lib)


def _num(x):
    try:
        return float(x)
    except Exception:
        return 0.0


def _percorso(file_rel):
    return os.path.join(DOWNLOAD_DIR, *file_rel.split("/"))


def file_esiste(file_rel):
    return os.path.isfile(_percorso(file_rel))


# ---------- esporta in MKV ----------
def _mkv_tracce(src_dir):
    """Dal master.m3u8 locale: liste audio [(file.ts, lang, etichetta)] e sub [(file.vtt, lang, etichetta)].
    Nel master la LANGUAGE è già il codice a 3 lettere (ita/eng/…) e NAME è l'etichetta."""
    audios, subs = [], []
    try:
        with open(os.path.join(src_dir, "master.m3u8"), encoding="utf-8") as f:
            txt = f.read()
    except Exception:
        return audios, subs
    for l in txt.splitlines():
        if not l.startswith("#EXT-X-MEDIA"):
            continue
        m_uri = re.search(r'URI="([^"]+)"', l)
        if not m_uri:
            continue
        m_lang = re.search(r'LANGUAGE="([^"]*)"', l)
        m_name = re.search(r'NAME="([^"]*)"', l)
        lang = (m_lang.group(1) if m_lang else "") or "und"
        name = (m_name.group(1) if m_name else "") or lang
        if "TYPE=AUDIO" in l:
            audios.append((m_uri.group(1).replace(".m3u8", ".ts"), lang, name))
        elif "TYPE=SUBTITLES" in l:
            subs.append((m_uri.group(1).replace(".m3u8", ".vtt"), lang, name))
    return audios, subs


def esporta_mkv(file_rel):
    """Converte il pacchetto HLS locale (video.ts + audio_N.ts + sub_N.vtt) in UN unico .mkv
    con ffmpeg in MODALITÀ COPY (nessuna ri-codifica → veloce, qualità identica). Le tracce audio
    e i sottotitoli restano selezionabili, con lingua ed etichetta. Ritorna (ok, percorso|errore)."""
    cartella = file_rel.split("/")[0]
    src_dir = os.path.join(DOWNLOAD_DIR, cartella)
    video = os.path.join(src_dir, "video.ts")
    if not os.path.isfile(video):
        return False, "Video mancante (forse è un vecchio download .mp4, non un pacchetto HLS)."
    audios = [(os.path.join(src_dir, ts), lang, name) for (ts, lang, name) in _mkv_tracce(src_dir)[0]
              if os.path.isfile(os.path.join(src_dir, ts))]
    subs = [(os.path.join(src_dir, vtt), lang, name) for (vtt, lang, name) in _mkv_tracce(src_dir)[1]
            if os.path.isfile(os.path.join(src_dir, vtt))]
    out = os.path.join(DOWNLOAD_DIR, cartella + ".mkv")

    cmd = [dl.ffmpeg_exe(), "-y", "-i", video]
    for (f, _l, _n) in audios + subs:
        cmd += ["-i", f]
    cmd += ["-map", "0:v:0"]
    idx = 1
    for _ in audios:
        cmd += ["-map", f"{idx}:a:0"]; idx += 1
    if not audios:
        # Anime (AnimeUnity): il master NON ha tracce audio separate, l'audio è
        # muxato dentro video.ts. Senza questo map l'MKV uscirebbe muto. Il "?"
        # rende il map opzionale (nessun errore se per assurdo video.ts è muto).
        cmd += ["-map", "0:a?"]
    for _ in subs:
        cmd += ["-map", f"{idx}:0"]; idx += 1
    cmd += ["-c:v", "copy", "-c:a", "copy"]
    if subs:
        cmd += ["-c:s", "srt"]                       # WebVTT -> SubRip (universale negli MKV)
    for oi, (_f, lang, name) in enumerate(audios):
        cmd += [f"-metadata:s:a:{oi}", "language=" + lang, f"-metadata:s:a:{oi}", "title=" + name]
    for oi, (_f, lang, name) in enumerate(subs):
        cmd += [f"-metadata:s:s:{oi}", "language=" + lang, f"-metadata:s:s:{oi}", "title=" + name]
    cmd += [out]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
    except Exception as e:
        return False, str(e)
    if r.returncode == 0 and os.path.isfile(out) and os.path.getsize(out) > 0:
        return True, out
    righe = [x for x in (r.stderr or "").strip().splitlines() if x]
    return False, "ffmpeg: " + (righe[-1] if righe else "errore sconosciuto")


def elimina_episodio(uid, file_rel):
    lib = leggi_libreria()
    voce = lib.get(uid)
    if voce:
        voce["episodi"] = [e for e in voce["episodi"] if e.get("file") != file_rel]
        if voce["episodi"]:
            lib[uid] = voce
        else:
            lib.pop(uid, None)
        _salva_libreria(lib)
    # elimina la cartella HLS (nuovo formato) oppure il singolo file (vecchi .mp4)
    primo = file_rel.split("/")[0]
    target = os.path.join(DOWNLOAD_DIR, primo)
    if os.path.isdir(target):
        shutil.rmtree(target, ignore_errors=True)
    else:
        try:
            os.remove(_percorso(file_rel))
        except Exception:
            pass


# ---------- job di download (CODA SERIALE) ----------
# vixcloud risponde 503 oltre ~16 connessioni per IP, e OGNI download apre fino a
# MAX_WORKERS=16 connessioni: se partissero tutti insieme si arriverebbe a 16xN
# connessioni -> 503 a raffica -> "segmento non scaricabile". Quindi i download
# vanno in CODA ed eseguiti UNO ALLA VOLTA da un unico worker (<=16 conn totali).
_coda = queue.Queue()
_worker = None
_worker_lock = threading.Lock()


def _assicura_worker():
    """Avvia (una sola volta, o lo riavvia se morto) il worker della coda."""
    global _worker
    with _worker_lock:
        if _worker is None or not _worker.is_alive():
            _worker = threading.Thread(target=_worker_loop, daemon=True)
            _worker.start()


def _worker_loop():
    while True:
        jid = _coda.get()
        try:
            job = _jobs.get(jid)
            if not job:
                continue
            # transizione "in coda" -> "in corso" sotto lock: se nel frattempo
            # l'utente ha annullato (stato != "in coda"), saltiamo il job.
            with _lock:
                if job["cancel"].is_set() or job["stato"] != "in coda":
                    parti = False
                else:
                    job["stato"] = "in corso"
                    job["msg"] = "Avvio…"
                    parti = True
            if not parti:
                shutil.rmtree(job["dest_dir"], ignore_errors=True)
                continue
            _esegui(job)
        except Exception:
            # un job non deve mai uccidere il worker: la coda deve proseguire.
            pass
        finally:
            _coda.task_done()


def _esegui(job):
    """Esegue un singolo download (chiamato dal worker, gia' in stato 'in corso')."""
    dest_dir = job["dest_dir"]

    def cb(frac, msg):
        job["frac"] = frac
        job["msg"] = msg

    try:
        dl.scarica(job["master_url"], dest_dir, height=job["height"], progress_cb=cb,
                   cancel_event=job["cancel"], tutte_le_tracce=job["tutte"])
        job["stato"] = "completato"
        job["frac"] = 1.0
        job["msg"] = "Completato"
        _registra(job["meta"], job["file"], job["titolo"])
    except dl.DownloadAnnullato:
        job["stato"] = "annullato"
        job["msg"] = "Annullato"
        shutil.rmtree(dest_dir, ignore_errors=True)
    except Exception as e:
        job["stato"] = "errore"
        job["errore"] = str(e)
        shutil.rmtree(dest_dir, ignore_errors=True)


def avvia_download(master_url, cartella, height, titolo, meta, tutte=True):
    """Accoda un download (pacchetto HLS in Download/<cartella>/). Il worker li
    esegue uno alla volta: il primo parte subito, gli altri restano 'in coda'."""
    jid = uuid.uuid4().hex[:8]
    dest_dir = os.path.join(DOWNLOAD_DIR, cartella)
    file_rel = cartella + "/master.m3u8"
    ev = threading.Event()
    job = {"id": jid, "titolo": titolo, "file": file_rel, "cartella": cartella,
           "stato": "in coda", "frac": 0.0, "msg": "In coda…", "cancel": ev,
           "meta": meta, "errore": None, "ts": time.time(),
           "master_url": master_url, "dest_dir": dest_dir, "height": height, "tutte": tutte}
    with _lock:
        _jobs[jid] = job
    _coda.put(jid)
    _assicura_worker()
    return jid


def lista_job():
    with _lock:
        return sorted(_jobs.values(), key=lambda j: j["ts"], reverse=True)


def annulla(jid):
    """Annulla un job. Se e' 'in corso' interrompe il download; se e' 'in coda'
    lo toglie subito (il worker lo saltera' quando lo estrae dalla coda)."""
    with _lock:
        j = _jobs.get(jid)
        if not j:
            return
        j["cancel"].set()
        if j["stato"] == "in coda":
            j["stato"] = "annullato"
            j["msg"] = "Annullato"


def rimuovi_job(jid):
    with _lock:
        _jobs.pop(jid, None)


def gia_in_coda(cartella):
    """True se quel titolo e' gia' scaricato, in download o in coda."""
    for j in lista_job():
        if j.get("cartella") == cartella and j["stato"] in ("in coda", "in corso", "completato"):
            return True
    return file_esiste(cartella + "/master.m3u8")
