"""
TrickFlix - AniList (GraphQL pubblico, niente chiave) per COPERTINE LANDSCAPE VERE.

Gli anime spesso hanno solo un poster verticale: ritagliarlo in una card orizzontale
viene male. AniList fornisce un `bannerImage` landscape (e un cover ad alta risoluzione
come fallback), agganciabile tramite l'`anilist_id` che AnimeUnity espone in ogni record.

API: POST https://graphql.anilist.co  (rate ~90/min) -> qui batch (50 id) + cache in RAM.
"""
import threading
import requests

_URL = "https://graphql.anilist.co"
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

_cache = {}          # anilist_id(int) -> {"banner": url|None, "cover": url|None}
_cache_q = {}        # titolo(lower) -> url|None
_lock = threading.Lock()

_BATCH = ("query($ids:[Int]){Page(perPage:50){media(id_in:$ids,type:ANIME){"
          "id bannerImage coverImage{extraLarge large}}}}")
_BYTITLE = ("query($q:String){Media(search:$q,type:ANIME){"
            "bannerImage coverImage{extraLarge large}}}")


def _post(query, variables):
    r = requests.post(_URL, json={"query": query, "variables": variables},
                      headers={"User-Agent": _UA, "Accept": "application/json"}, timeout=20)
    r.raise_for_status()
    return r.json().get("data") or {}


def _cover(coverimg):
    coverimg = coverimg or {}
    return coverimg.get("extraLarge") or coverimg.get("large")


def info(ids):
    """{id: {banner, cover}} per una lista di anilist_id (batch da 50, in cache)."""
    voluti, mancanti, out = [], [], {}
    for i in ids:
        try:
            i = int(i)
        except (TypeError, ValueError):
            continue
        voluti.append(i)
    with _lock:
        for i in voluti:
            if i in _cache:
                out[i] = _cache[i]
            else:
                mancanti.append(i)
    for k in range(0, len(mancanti), 50):
        chunk = mancanti[k:k + 50]
        try:
            media = (_post(_BATCH, {"ids": chunk}).get("Page") or {}).get("media") or []
        except Exception:
            media = []
        trovati = set()
        for m in media:
            rec = {"banner": m.get("bannerImage"), "cover": _cover(m.get("coverImage"))}
            with _lock:
                _cache[m["id"]] = rec
            out[m["id"]] = rec
            trovati.add(m["id"])
        for i in chunk:                       # id non risolti: cache vuota (non riprovare)
            if i not in trovati:
                with _lock:
                    _cache[i] = {"banner": None, "cover": None}
                out[i] = _cache[i]
    return out


def banner(anilist_id):
    """Banner landscape (fallback al cover) per un singolo anilist_id."""
    if not anilist_id:
        return None
    rec = info([anilist_id]).get(int(anilist_id)) or {}
    return rec.get("banner") or rec.get("cover")


def cerca_banner(titolo):
    """Banner/cover cercando per TITOLO (quando manca l'anilist_id). In cache."""
    if not titolo:
        return None
    chiave = titolo.strip().lower()
    with _lock:
        if chiave in _cache_q:
            return _cache_q[chiave]
    url = None
    try:
        m = _post(_BYTITLE, {"q": titolo}).get("Media") or {}
        url = m.get("bannerImage") or _cover(m.get("coverImage"))
    except Exception:
        url = None
    with _lock:
        _cache_q[chiave] = url
    return url
