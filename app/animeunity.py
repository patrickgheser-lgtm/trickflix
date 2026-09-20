"""
TrickFlix - AnimeUnity via API diretta (niente browser/estensione).
Verificato sul sito vivo (Laravel + vixcloud, stesso backend di StreamingCommunity).

Flusso:
  1) GET /            -> cookie sessione + <meta csrf-token>
  2) POST /livesearch -> {records:[{id,slug,title,imageurl,plot,dub,...}]}   (serve X-CSRF-TOKEN)
  3) GET /anime/{id}-{slug} -> componente <video-player episodes="[{id,number,...}]">
  4) GET /embed-url/{ep_id} -> URL embed vixcloud
  5) pagina embed -> window.downloadUrl = MP4 diretto (1080p)  [+ vixcloud m3u8 disponibile]

Dub vs Originale: su AnimeUnity sono ENTRY separate (campo 'dub'); l'utente sceglie in ricerca.
Dominio risolto in automatico da dominio() qui sotto (Startpage + guida, validato col backend
reale /archivio/get-animes e normalizzato per i redirect www) + override app/dominio_au.txt.
"""
import os
import re
import json
import time
import html
import requests
from urllib.parse import urlparse

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

# --- risoluzione robusta e LONGEVA del dominio (stesso schema di streamingcommunity.py) ---
# FONTE PRINCIPALE: domains.json mantenuti su GitHub, auto-aggiornati da una GitHub Action (formato
# JSON stabile, coprono AU + SC). LISTA: si prova in ordine, aggiungerne altri = più longevità.
GITHUB_DOMAINS = [
    "https://raw.githubusercontent.com/RunAway189/StreamingCommunity/main/.github/.domain/domains.json",
]
STARTPAGE = "https://www.startpage.com/sp/search"
# tante guide ridondanti: se una cambia/sparisce o linka un clone, le altre coprono; la
# validazione (backend reale) scarta comunque i cloni. Aggiungerne è gratis = più longevità.
GUIDE = [
    "https://www.giardiniblog.it/animeunity-nuovo-indirizzo/",
    "https://www.capitolivm.it/streaming-film-serie-tv/animeunity/",
    "https://www.tuttotek.it/web-social/guide-web-social/animeunity-nuovo-indirizzo-e-link",
]
# cattura "animeunity.so", "animeunityz.xxx" (TLD anche LUNGO -> {2,} non {2,6}), con/senza schema/www
_PAT_DOM = r'(?:https?://)?(?:www\.)?(animeunity[a-z0-9\-]*\.[a-z]{2,})'
_TLD_JUNK = {"png", "jpg", "jpeg", "gif", "webp", "svg", "css", "js", "html", "htm",
             "php", "ico", "woff", "woff2", "mp4", "json", "xml"}
_CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dominio_au_cache.json")
_CACHE_TTL = 12 * 3600
_DOM_BASE = None    # base completa GIA' normalizzata post-redirect (es. https://www.animeunity.so)

_S = None
_CSRF = ""
_BASE = ""
_HOME_HTML = None   # homepage scaricata da _ensure(), riusata da home() (evita di riscaricare 211KB)


def _h(extra=None):
    h = {"User-Agent": UA, "Accept-Language": "it-IT,it;q=0.9"}
    if extra:
        h.update(extra)
    return h


def _get(url, params=None, timeout=15):
    try:
        return requests.get(url, params=params, headers=_h(), timeout=timeout).text
    except Exception:
        return ""


def _estrai_domini(text):
    out = []
    for d in re.findall(_PAT_DOM, text or "", re.I):
        d = d.lower().strip(".")
        if d.rsplit(".", 1)[-1] in _TLD_JUNK:
            continue
        if d not in out:
            out.append(d)
    return out


def _override_manuale():
    """Dominio AU forzato a mano in app/dominio_au.txt (vince su tutto)."""
    f = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dominio_au.txt")
    try:
        with open(f, encoding="utf-8") as fh:
            d = fh.read().strip()
        return d.replace("https://", "").replace("http://", "").strip("/ ") or None
    except Exception:
        return None


def _valida(host, timeout=8):
    """Ritorna la BASE normalizzata (https://host-finale, dopo eventuali redirect www) se
    'host' e' il VERO AnimeUnity, altrimenti None. Prova definitiva: il backend reale
    /archivio/get-animes risponde JSON con 'records' (i cloni danno HTML/404). La
    normalizzazione post-redirect risolve da sola il caso animeunity.so -> www.animeunity.so
    (un POST verso il dominio sbagliato verrebbe degradato a GET -> 405)."""
    if not host:
        return None
    try:
        s = requests.Session()
        s.headers.update(_h())
        home = s.get("https://" + host + "/", timeout=timeout, allow_redirects=True)
        if home.status_code != 200:
            return None
        u = urlparse(str(home.url))
        base = f"{u.scheme}://{u.netloc}"
        m = re.search(r'csrf-token"\s+content="([^"]+)"', home.text)
        if not m:
            return None
        hdr = {"X-CSRF-TOKEN": m.group(1), "X-Requested-With": "XMLHttpRequest",
               "Content-Type": "application/json"}
        body = {"title": False, "type": False, "year": False, "order": "Popolarità",
                "status": False, "genres": [], "offset": 0, "dubbed": False, "season": False}
        r = s.post(base + "/archivio/get-animes", headers=hdr, data=json.dumps(body), timeout=timeout)
        if "application/json" in r.headers.get("content-type", "") and isinstance(r.json().get("records"), list):
            return base
    except Exception:
        pass
    return None


def _cache_get(solo_fresco=False):
    """Ultima base nota-funzionante. Di default a QUALSIASI età (rete di sicurezza: se il vecchio
    dominio è ancora vivo l'app non si rompe); solo_fresco=True solo se scritta da <_CACHE_TTL."""
    try:
        with open(_CACHE, encoding="utf-8") as f:
            e = json.load(f)
        base = e.get("base")
        if base and (not solo_fresco or (time.time() - e.get("ts", 0)) < _CACHE_TTL):
            return base
    except Exception:
        pass
    return None


def _cache_set(base):
    if not base:
        return
    try:
        with open(_CACHE, "w", encoding="utf-8") as f:
            json.dump({"base": base, "ts": time.time()}, f)
    except Exception:
        pass


def _github_dom():
    """Dominio AU dai domains.json mantenuti su GitHub (fonte JSON stabile e auto-aggiornata).
    Prova ogni URL della lista e ritorna il primo dominio valido."""
    for url in GITHUB_DOMAINS:
        try:
            j = requests.get(url, headers=_h(), timeout=10).json()
            d = (j.get("animeunity") or {}).get("full_url", "").split("//")[-1].split("/")[0]
            if d:
                return d
        except Exception:
            continue
    return None


def _candidati():
    """Genera candidati AU in modo LAZY (GitHub JSON -> Startpage -> guide). Chi chiama valida e
    si ferma al primo valido: se GitHub basta, le guide non vengono scaricate (efficiente)."""
    visti = set()

    def nuovi(domini):
        for d in domini:
            if d and d not in visti:
                visti.add(d)
                yield d

    gh = _github_dom()
    yield from nuovi([gh] if gh else [])
    yield from nuovi(_estrai_domini(_get(STARTPAGE, {"query": "animeunity", "cat": "web"})))
    for u in GUIDE:
        yield from nuovi(_estrai_domini(_get(u)))


def dominio(forza=False):
    """Base completa del VERO AnimeUnity (es. 'https://www.animeunity.so'), normalizzata per i
    redirect e risolta in modo LONGEVO (si auto-ripara). Ordine: override -> cache FRESCA
    rivalidata -> scoperta da molte fonti -> RETE DI SICUREZZA sull'ultima base nota-funzionante
    (qualsiasi età) se ancora viva. La validazione (backend reale /archivio/get-animes) è il
    vero giudice, quindi non serve indovinare la forma dell'URL. None solo se tutto è morto."""
    global _DOM_BASE
    if _DOM_BASE and not forza:
        return _DOM_BASE
    ov = _valida(_override_manuale())
    if ov:
        _DOM_BASE = ov
        _cache_set(ov)
        return _DOM_BASE
    if not forza:
        fresco = _cache_get(solo_fresco=True)
        if fresco and _valida(urlparse(fresco).netloc):
            _DOM_BASE = fresco
            return _DOM_BASE
    for d in _candidati():
        base = _valida(d)
        if base:
            _DOM_BASE = base
            _cache_set(base)
            return _DOM_BASE
    ultimo = _cache_get()                       # scoperta fallita: ultima base ancora viva?
    if ultimo:
        base = _valida(urlparse(ultimo).netloc)
        if base:
            _DOM_BASE = base
            _cache_set(base)
            return _DOM_BASE
    return None


def _ensure(base):
    """Sessione con cookie + token CSRF (creata una volta per dominio). Normalizza il base al
    dominio EFFETTIVO dopo i redirect (es. animeunity.so -> www.animeunity.so): senza questo, i
    POST verso il dominio pre-redirect vengono degradati a GET -> 405. Ritorna (sessione, csrf, base)."""
    global _S, _CSRF, _BASE, _HOME_HTML
    if _S is None or _BASE != base:
        _S = requests.Session()
        _S.headers.update({"User-Agent": UA, "Accept-Language": "it-IT,it;q=0.9"})
        home = _S.get(base + "/", timeout=15, allow_redirects=True)
        u = urlparse(str(home.url))
        base = f"{u.scheme}://{u.netloc}"     # dominio finale reale
        _HOME_HTML = home.text          # la riusa home() invece di riscaricare 211KB
        m = re.search(r'csrf-token"\s+content="([^"]+)"', home.text)
        _CSRF = m.group(1) if m else ""
        _BASE = base
    return _S, _CSRF, _BASE


def _nome(rec):
    """Titolo robusto: il campo 'title' (italiano) spesso è null -> usa l'inglese."""
    return rec.get("title") or rec.get("title_eng") or rec.get("title_it") or "Senza titolo"


def _record(rec):
    return {"id": rec["id"], "slug": rec.get("slug", ""), "title": _nome(rec),
            "title_eng": rec.get("title_eng"), "title_it": rec.get("title_it"),
            "title_jp": rec.get("title"), "anilist_id": rec.get("anilist_id"),
            "poster": rec.get("imageurl"), "landscape": rec.get("imageurl_cover") or rec.get("cover"),
            "plot": rec.get("plot", ""), "dub": bool(rec.get("dub")),
            "episodi": rec.get("episodes_count")}


def _attr_json(html_text, attr):
    """Estrae il JSON di un attributo Vue STATICO della home (es. animes="...&quot;...").
    AnimeUnity rende i suoi slider embeddando i dati negli attributi dei componenti Vue."""
    m = re.search(r'\b%s="(.*?)"' % re.escape(attr), html_text, re.S)
    if not m:
        return None
    try:
        return json.loads(html.unescape(m.group(1)))
    except Exception:
        return None


def _anime_item(rec):
    """Mappa un record anime nel formato dei caroselli della home (come streamingcommunity.home).
    landscape = banner widescreen (imageurl_cover); poster = locandina verticale (imageurl)."""
    season = str(rec.get("season") or "")
    quando = season + " " + str(rec.get("date") or rec.get("created_at") or "")
    anno = re.search(r"(?:19|20)\d{2}", quando)
    return {"id": rec["id"], "slug": rec.get("slug", ""), "name": _nome(rec), "type": "anime",
            "poster": rec.get("imageurl"),
            "landscape": rec.get("imageurl_cover") or rec.get("cover") or rec.get("imageurl"),
            "background": rec.get("imageurl_cover") or rec.get("cover"),
            "score": rec.get("score"), "year": anno.group(0) if anno else "",
            "dub": bool(rec.get("dub")), "plot": rec.get("plot", ""),
            "anilist_id": rec.get("anilist_id"), "episodi": rec.get("episodes_count")}


def home(base, popolari=False):
    """Righe della homepage AnimeUnity per i caroselli TrickFlix.
    Ritorna [(label, [item, ...])] con item nello stesso formato di streamingcommunity.home().
    'in evidenza' + 'ultimi episodi' arrivano dalla STESSA homepage (0 richieste extra);
    'popolari' (POST /archivio/get-animes) è opzionale (popolari=True) perché aggiunge una
    richiesta di rete e rallenta l'avvio."""
    global _HOME_HTML
    s, csrf, base = _ensure(base)
    righe = []
    pagina = _HOME_HTML             # riusa la homepage scaricata da _ensure()
    _HOME_HTML = None               # consuma: la prossima volta riscarica fresco
    if not pagina:
        try:
            pagina = s.get(base + "/", timeout=20).text
        except Exception:
            return righe

    # 1) carosello "in evidenza" (anime in tendenza scelti dal sito)
    car = _attr_json(pagina, "animes")
    if isinstance(car, list):
        items = [_anime_item(a) for a in car if a.get("id") and a.get("imageurl_cover")]
        if items:
            righe.append(("Anime in evidenza", items[:24]))

    # 2) ultimi episodi (ogni voce ha l'anime annidato; dedup per anime)
    ij = _attr_json(pagina, "items-json")
    if isinstance(ij, dict):
        visti, items = set(), []
        for ep in (ij.get("data") or []):
            an = ep.get("anime") or {}
            aid = an.get("id")
            if not aid or aid in visti or not an.get("imageurl_cover"):
                continue
            visti.add(aid)
            items.append(_anime_item(an))
        if items:
            righe.append(("Ultimi episodi", items[:24]))

    # 3) anime popolari (archivio ordinato per popolarita') — OPZIONALE: costa 1 richiesta
    if popolari:
        try:
            hdr = {"X-CSRF-TOKEN": csrf, "X-Requested-With": "XMLHttpRequest",
                   "Content-Type": "application/json"}
            body = {"title": False, "type": False, "year": False, "order": "Popolarità",
                    "status": False, "genres": [], "offset": 0, "dubbed": False, "season": False}
            j = s.post(base + "/archivio/get-animes", headers=hdr, data=json.dumps(body), timeout=15).json()
            items = [_anime_item(r) for r in (j.get("records") or [])
                     if r.get("id") and r.get("imageurl_cover")]
            if items:
                righe.append(("Anime popolari", items[:24]))
        except Exception:
            pass

    return righe


def cerca(query, base):
    """Ricerca AnimeUnity completa via /archivio/get-animes (tutti i risultati,
    con titoli corretti). Fallback a /livesearch se l'endpoint cambia."""
    s, csrf, base = _ensure(base)
    hdr = {"X-CSRF-TOKEN": csrf, "X-Requested-With": "XMLHttpRequest",
           "Content-Type": "application/json"}
    out, visti, offset = [], set(), 0
    try:
        while len(out) < 60:
            body = {"title": query, "type": False, "year": False, "order": "Più visti",
                    "status": False, "genres": [], "offset": offset, "dubbed": False, "season": False}
            r = s.post(base + "/archivio/get-animes", headers=hdr, data=json.dumps(body), timeout=15)
            r.raise_for_status()
            j = r.json()
            recs = j.get("records", [])
            if not recs:
                break
            for rec in recs:
                if rec["id"] in visti:
                    continue
                visti.add(rec["id"])
                out.append(_record(rec))
            offset += len(recs)
            if offset >= j.get("tot", offset):
                break
        if out:
            return out
    except Exception:
        pass
    # fallback: livesearch (rapido ma limitato)
    try:
        r = s.post(base + "/livesearch",
                   headers={"X-CSRF-TOKEN": csrf, "X-Requested-With": "XMLHttpRequest"},
                   data={"title": query}, timeout=15)
        r.raise_for_status()
        return [_record(rec) for rec in r.json().get("records", [])[:60]]
    except Exception:
        return out


def episodi(anime_id, slug, base):
    """Lista episodi [{id, number}] dalla pagina anime."""
    s, _, base = _ensure(base)
    ap = s.get(f"{base}/anime/{anime_id}-{slug}", timeout=15)
    m = re.search(r'episodes="([^"]+)"', ap.text)
    if not m:
        return []
    try:
        eps = json.loads(html.unescape(m.group(1)))
    except Exception:
        return []
    return [{"id": e["id"], "number": str(e.get("number"))} for e in eps]


def flusso_episodio(ep_id, base):
    """Ritorna (url_video, headers). url_video = MP4 diretto (window.downloadUrl)."""
    s, _, base = _ensure(base)
    embed = s.get(f"{base}/embed-url/{ep_id}", timeout=15).text.strip()
    if not embed.startswith("http"):
        return None, None
    er = s.get(embed, headers={"Referer": base + "/"}, timeout=15).text
    m = re.search(r"window\.downloadUrl\s*=\s*['\"]([^'\"]+)", er)
    if m:
        return m.group(1), {"referer": embed}
    return None, None


def m3u8_episodio(ep_id, base):
    """m3u8 vixcloud dell'episodio (qualita' + selezione audio nel player)."""
    import vixcloud
    s, _, base = _ensure(base)
    embed = s.get(f"{base}/embed-url/{ep_id}", timeout=15).text.strip()
    if not embed.startswith("http"):
        return None
    return vixcloud.estrai_m3u8(embed, session=s, referer=base + "/")
