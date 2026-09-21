"""
TrickFlix - VixSrc: sorgente ALTERNATIVA per film e serie (stesso backend vixcloud di SC).

Perche' esiste: StreamingCommunity ha smesso di concedere l'FHD agli utenti non Premium
(nell'URL embed non mette piu' canPlayFHD) e l'app resta tappata a 720p. VixSrc e' un
frontend PUBBLICO sulla STESSA libreria vixcloud - stessi video id, es. Matrix = 214325 -
che invece emette token con canPlayFHD=1. Oggi film e serie sono comunque codificati solo
a 480/720 (verificato su 10 titoli), quindi la qualita' non cambia SUBITO; il guadagno e':
  - se rimettono le codifiche 1080p, da qui arrivano in automatico (da SC no);
  - e' una seconda strada verso lo stesso video se il frontend SC si rompe.

API (documentata sul sito):
  GET /api/movie/{tmdb_id}?lang=it              -> {"src": "/embed/...&canPlayFHD=1"}
  GET /api/tv/{tmdb_id}/{stagione}/{episodio}?lang=it
La pagina embed ha la stessa struttura di vixcloud: `vixcloud.estrai_m3u8` funziona invariato
(riconosce canPlayFHD e aggiunge &h=1). L'm3u8 esce con CORS '*', quindi hls.js lo riproduce
diretto come quello di SC.

Il dominio puo' ruotare come tutti gli altri: vedi dominio(), stesso schema longevo di
streamingcommunity.py / animeunity.py (piu' fonti + validazione col backend VERO + cache
mai buttata finche' funziona + override manuale).
"""
import os
import re
import json
import time

import vixcloud

try:
    from curl_cffi import requests as _cffi
except Exception:                       # pragma: no cover
    _cffi = None
import requests as _requests

UA = vixcloud.UA

# Domini noti da cui partire, nel caso ruotino.
SEED = ["vixsrc.to"]
# FONTE PRINCIPALE di scoperta: progetti GitHub ATTIVI che usano questa stessa API. Se VixSrc
# cambia dominio, loro lo aggiornano e noi lo leggiamo da li'. Sono fetch RAW diretti, quindi
# niente rate limit (l'API di ricerca GitHub invece lo ha). Aggiungerne altri qui e' gratis.
GITHUB_REPOS = [
    "Paliddo86/stremio-vixsrc-addon",
    "scageto/CasaFlix",
    "Vinesh03/VixStream",
    "Redin00/streamapp-rdn",
    "Inside4ndroid/TMDB-Embed-API",
]
GITHUB_FILES = ["README.md", "readme.md", "package.json", "src/index.js", "index.js", "config.js"]
GITHUB_RICERCA = "https://api.github.com/search/repositories"
STARTPAGE = "https://www.startpage.com/sp/search"
_PAT_DOM = r'(?:https?://)?(?:www\.)?(vix[a-z0-9\-]*\.[a-z]{2,})'
_TLD_JUNK = {"png", "jpg", "jpeg", "gif", "webp", "svg", "css", "js", "html", "htm",
             "php", "ico", "woff", "woff2", "mp4", "json", "xml", "py", "ts", "md",
             "vercel", "onrender", "herokuapp"}   # ultimi: deploy di terzi, non il sito vero
# id TMDB usato per validare un dominio candidato: 603 = Matrix, c'e' di sicuro.
_TMDB_PROVA = 603

import percorsi
_CACHE = percorsi.dato("dominio_vixsrc_cache.json")
_CACHE_TTL = 12 * 3600
_BASE = None


def _h(extra=None):
    h = {"User-Agent": UA, "Accept-Language": "it-IT,it;q=0.9"}
    if extra:
        h.update(extra)
    return h


def _get(url, params=None, headers=None, timeout=20):
    """GET che passa eventuali protezioni anti-bot (curl_cffi impersona Chrome)."""
    hdr = _h(headers)
    if _cffi is not None:
        try:
            r = _cffi.get(url, params=params, headers={k: v for k, v in hdr.items() if k != "User-Agent"},
                          impersonate="chrome", timeout=timeout)
            if r.status_code == 200:
                return r
        except Exception:
            pass
    try:
        return _requests.get(url, params=params, headers=hdr, timeout=timeout)
    except Exception:
        return None


def _estrai_domini(text):
    out = []
    for d in re.findall(_PAT_DOM, text or "", re.I):
        d = d.lower().strip(".")
        if d.rsplit(".", 1)[-1] in _TLD_JUNK or not d.startswith("vixsrc"):
            continue
        if d not in out:
            out.append(d)
    return out


def _override_manuale():
    f = percorsi.override("dominio_vixsrc.txt")
    if not f:
        return None
    try:
        with open(f, encoding="utf-8") as fh:
            d = fh.read().strip()
        return d.replace("https://", "").replace("http://", "").strip("/ ") or None
    except Exception:
        return None


def _valida(host, timeout=15):
    """True se 'host' e' davvero VixSrc: l'API risponde JSON con un src /embed/.
    E' la prova col backend REALE, quindi indipendente da come cambia il sito."""
    if not host:
        return False
    try:
        r = _get(f"https://{host}/api/movie/{_TMDB_PROVA}", params={"lang": "it"},
                 headers={"Referer": f"https://{host}/movie/{_TMDB_PROVA}"}, timeout=timeout)
        if not r or r.status_code != 200:
            return False
        if "application/json" not in r.headers.get("content-type", ""):
            return False
        return "/embed/" in (r.json().get("src") or "")
    except Exception:
        return False


def _cache_get(solo_fresco=False):
    try:
        with open(_CACHE, encoding="utf-8") as f:
            e = json.load(f)
        d = e.get("dom")
        if d and (not solo_fresco or (time.time() - e.get("ts", 0)) < _CACHE_TTL):
            return d
    except Exception:
        pass
    return None


def _cache_set(dom):
    if not dom:
        return
    try:
        with open(_CACHE, "w", encoding="utf-8") as f:
            json.dump({"dom": dom, "ts": time.time()}, f)
    except Exception:
        pass


def _testo(url, timeout=12):
    r = _get(url, timeout=timeout)
    return r.text if (r is not None and r.status_code == 200) else ""


def _da_repo(full_name):
    """Domini vixsrc citati nei file di un repo GitHub (si ferma al primo file utile)."""
    for f in GITHUB_FILES:
        doms = _estrai_domini(_testo(f"https://raw.githubusercontent.com/{full_name}/HEAD/{f}"))
        if doms:
            return doms
    return []


def _repo_attivi():
    """Altri progetti che usano vixsrc, cercati su GitHub: cosi' l'elenco fisso non invecchia.
    Se l'API e' a rate limit o cambia, si ignora e si va avanti con le altre fonti."""
    try:
        r = _requests.get(GITHUB_RICERCA, params={"q": "vixsrc", "sort": "updated", "per_page": 8},
                          headers={"User-Agent": "TrickFlix", "Accept": "application/vnd.github+json"},
                          timeout=15)
        if r.status_code != 200:
            return []
        return [it["full_name"] for it in r.json().get("items", [])][:6]
    except Exception:
        return []


def _candidati():
    """Candidati in modo LAZY, per fonte, dalla piu' affidabile: domini noti -> progetti GitHub
    che usano VixSrc (si aggiornano da soli quando il dominio ruota) -> altri progetti trovati
    cercando su GitHub -> ricerca web. Chi chiama valida e si ferma al primo buono, quindi di
    norma non si scarica nulla oltre al primo tentativo."""
    visti = set()

    def nuovi(lista):
        for d in lista:
            if d and d not in visti:
                visti.add(d)
                yield d

    yield from nuovi(SEED)
    for repo in GITHUB_REPOS:
        yield from nuovi(_da_repo(repo))
    for repo in _repo_attivi():
        if repo not in GITHUB_REPOS:
            yield from nuovi(_da_repo(repo))
    yield from nuovi(_estrai_domini(_testo(STARTPAGE + "?query=vixsrc&cat=web", timeout=20)))


def dominio(forza=False):
    """Base di VixSrc (es. 'https://vixsrc.to'), risolta in modo LONGEVO:
    override manuale -> cache FRESCA rivalidata -> candidati (noti + ricerca) ->
    RETE DI SICUREZZA sull'ultimo dominio noto se ancora vivo. None solo se tutto e' morto."""
    global _BASE
    if _BASE and not forza:
        return _BASE
    ov = _override_manuale()
    if _valida(ov):
        _BASE = "https://" + ov
        _cache_set(ov)
        return _BASE
    if not forza:
        fresco = _cache_get(solo_fresco=True)
        if fresco and _valida(fresco):
            _BASE = "https://" + fresco
            return _BASE
    for d in _candidati():
        if _valida(d):
            _BASE = "https://" + d
            _cache_set(d)
            return _BASE
    ultimo = _cache_get()                    # scoperta fallita: il vecchio regge ancora?
    if ultimo and _valida(ultimo):
        _BASE = "https://" + ultimo
        _cache_set(ultimo)
        return _BASE
    return None


def m3u8(tmdb_id, stagione=None, episodio=None):
    """m3u8 del film (solo tmdb_id) o dell'episodio (tmdb_id + stagione + episodio).
    None se VixSrc non ha il titolo o non e' raggiungibile: il chiamante ripiega su SC."""
    if not tmdb_id:
        return None
    base = dominio()
    if not base:
        return None
    try:
        if stagione and episodio:
            via = f"/tv/{int(tmdb_id)}/{int(stagione)}/{int(episodio)}"
        elif episodio:                        # serie senza stagioni (numerazione unica)
            via = f"/tv/{int(tmdb_id)}/1/{int(episodio)}"
        else:
            via = f"/movie/{int(tmdb_id)}"
    except (TypeError, ValueError):
        return None
    ref = base + via
    r = _get(base + "/api" + via, params={"lang": "it"}, headers={"Referer": ref})
    if not r or r.status_code != 200 or "application/json" not in r.headers.get("content-type", ""):
        return None
    try:
        src = r.json().get("src")
    except Exception:
        return None
    if not src:
        return None
    embed = src if src.startswith("http") else base + src
    try:
        return vixcloud.estrai_m3u8(embed, referer=ref)
    except Exception:
        return None
