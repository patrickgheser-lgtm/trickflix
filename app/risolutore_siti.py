"""
TrickFlix - Risolutore dinamico dei domini.
Legge ogni volta la struttura HTML del megathread e ricava il dominio aggiornato
di un sito (es. "456movie"), così se il dominio cambia l'app si adegua da sola.
"""
import re
import os
import json
import time
import requests

# Cache su disco dei domini risolti: la risoluzione (giardiniblog) costa ~1-3s ed è il grosso
# del cold start. I domini cambiano di rado -> li teniamo in cache 6h, così all'apertura
# dell'app sono istantanei. (Se un dominio cambia, al massimo dopo 6h si ri-risolve; in caso
# di sito irraggiungibile i chiamanti gestiscono già il fallback.)
_CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "domini_cache.json")
_CACHE_TTL = 6 * 3600


def _cache_get(quale):
    try:
        with open(_CACHE_FILE, encoding="utf-8") as f:
            e = json.load(f).get(quale)
        if e and (time.time() - e.get("ts", 0)) < _CACHE_TTL and e.get("dom"):
            return e["dom"]
    except Exception:
        pass
    return None


def _cache_set(quale, dom):
    if not dom:
        return
    try:
        data = {}
        if os.path.exists(_CACHE_FILE):
            with open(_CACHE_FILE, encoding="utf-8") as f:
                data = json.load(f)
        data[quale] = {"dom": dom, "ts": time.time()}
        with open(_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f)
    except Exception:
        pass


MEGATHREAD_FILM = "https://rentry.co/megathread-movies-and-tv"
MEGATHREAD_ANIME = "https://rentry.org/megathread-anime"
MEGATHREAD_DEFAULT = MEGATHREAD_FILM

# Giardiniblog tiene aggiornati i domini di StreamingCommunity e AnimeUnity
GIARDINI = {
    "streamingcommunity": "https://www.giardiniblog.it/streamingcommunity-nuovo-link/",
    "animeunity": "https://www.giardiniblog.it/animeunity-nuovo-indirizzo/",
}
_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                     "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"}


def dominio_corrente(quale, timeout=20):
    """
    Ritorna il dominio attuale (es. 'streaming-community.watch' o 'animeunity.so')
    leggendo la pagina giardiniblog dedicata. None se non trovato.
    'quale' = 'streamingcommunity' oppure 'animeunity'.
    """
    cached = _cache_get(quale)          # disco: istantaneo se risolto di recente
    if cached:
        return cached
    url = GIARDINI.get(quale)
    if not url:
        return None
    try:
        html = requests.get(url, headers=_UA, timeout=timeout).text
    except Exception:
        return None
    pat = r'https?://(?:www\.)?((?:streaming[\-]?community|animeunity)[a-z0-9\-]*\.[a-z]{2,})'
    trovati = re.findall(pat, html, re.I)
    # primo dominio citato nella pagina = quello attuale
    dom = trovati[0].lower() if trovati else None
    _cache_set(quale, dom)
    return dom


def ottieni_dominio_sito(id_sito, megathread_url=MEGATHREAD_DEFAULT, timeout=20):
    """
    Scarica il megathread, trova l'heading con id="{id_sito}" e ne estrae l'URL
    del sito (il primo link http dopo quell'id). Ritorna la base 'https://dominio'
    (senza slash finale) oppure None se non trovato.
    """
    html = requests.get(
        megathread_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=timeout
    ).text

    pos = html.find(f'id="{id_sito}"')
    if pos == -1:
        return None

    m = re.search(r'href="(https?://[^"]+)"', html[pos:])
    if not m:
        return None

    return re.match(r'(https?://[^/]+)', m.group(1)).group(1)


def sito_raggiungibile(base, timeout=6):
    """
    True se il dominio risponde (anche con 4xx: il server è vivo).
    False se non carica (DNS fallito, connessione rifiutata, timeout): dominio probabilmente cambiato.
    """
    if not base:
        return False
    try:
        requests.get(base, headers={"User-Agent": "Mozilla/5.0"}, timeout=timeout, allow_redirects=True)
        return True
    except requests.RequestException:
        return False


def costruisci_url_watch(base, tipo, tmdb_id):
    """
    Costruisce l'URL di visione 456movie a partire dalla base risolta:
      film  -> {base}/movie/watch/{tmdb_id}
      serie -> {base}/tv/watch/{tmdb_id}
    """
    segmento = "movie" if tipo == "movie" else "tv"
    return f"{base}/{segmento}/watch/{tmdb_id}"
