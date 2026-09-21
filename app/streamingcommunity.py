"""
TrickFlix - StreamingCommunity (vero sito, backend vixcloud) via API diretta.
Niente browser/estensione/proxy: l'm3u8 vixcloud si gioca diretto (CORS *, no Referer).

Flusso (verificato live):
  - dominio: da tuttotek (punta al SC vero) -> es. streamingcommunityz.us
  - ricerca: GET /it/search?q=...  (Accept json) -> {data:[{id,slug,name,type,...}]}
  - film:    GET /it/iframe/{id}                       -> <iframe vixcloud> -> m3u8
  - serie:   GET /it/titles/{id}-{slug}[?season=N]     -> data-page: seasons + loadedSeason.episodes
             GET /it/iframe/{id}?episode_id={ep}       -> <iframe vixcloud> -> m3u8
  - dub/originale = tracce AUDIO nell'm3u8 (ita + eng), scelte nel player.
"""
import re
import os
import json
import time
import html as _html
import requests

import threading
import vixcloud
from vixcloud import estrai_m3u8, UA

# Startpage = risultati Google senza blocco anti-bot (i motori diretti danno 202/vuoto). Poi
# TANTE guide ridondanti: SC ruota e ciascuna guida a volte linka solo cloni o è irraggiungibile,
# ma basta che UNA abbia il dominio vero (la validazione scarta i cloni). Aggiungerne altre qui
# è gratis: più fonti = più longevità. (capitolivm oggi ha il dominio reale, giardiniblog no.)
# FONTE PRINCIPALE (la più longeva): domains.json mantenuti su GitHub, auto-aggiornati da una
# GitHub Action. Formato JSON STABILE (non si rompe come lo scraping HTML) e coprono SC + AnimeUnity.
# È una LISTA: si prova in ordine e si usa il primo che risponde -> aggiungerne altri = più longevità
# (basta incollare qui l'URL raw di un altro repo che espone lo stesso schema).
GITHUB_DOMAINS = [
    "https://raw.githubusercontent.com/RunAway189/StreamingCommunity/main/.github/.domain/domains.json",
]
STARTPAGE = "https://www.startpage.com/sp/search"
GUIDE = [
    "https://www.capitolivm.it/streaming-film-serie-tv/streaming-community/",
    "https://www.epgitalia.tv/streaming-community-nuovo-link/",
    "https://www.giardiniblog.it/streamingcommunity-nuovo-link/",
    "https://www.tuttotek.it/web-social/guide-web-social/streamingcommunity-nuovo-indirizzo-e-link",
    "https://www.nuovosito.com/nuovo-sito-streamingcommunity-luglio-2025/",
]
# domini SC candidati: cattura "streamingcommunityz.pizza/.pl/.bargains" (TLD anche LUNGO ->
# {2,} non {2,6}, altrimenti si tronca), "streaming-community.observer" (col trattino), con o
# senza schema/www. Chi valida scarta comunque i cloni.
_PAT_DOM = r'(?:https?://)?(?:www\.)?(streaming[\-]?communit[a-z0-9\-]*\.[a-z]{2,})'
# "tld" che in realtà sono estensioni di file/path finiti nel testo -> da scartare
_TLD_JUNK = {"html", "htm", "php", "asp", "aspx", "jpg", "jpeg", "png", "gif",
             "css", "js", "webp", "svg", "json", "xml", "ico", "woff", "woff2", "mp4"}

# cache su disco del dominio SC risolto. IMPORTANTE per la longevità: la cache NON si butta mai
# "a scadenza" — un dominio SC ruotato di solito continua a funzionare per giorni, quindi l'ultimo
# noto-funzionante viene sempre RIVALIDATO e, se ancora vivo, usato. Si ri-scopre solo quando è
# davvero morto. Il TTL serve solo a decidere quando PROVARE a cercarne uno più fresco.
import percorsi
_CACHE = percorsi.dato("dominio_sc_cache.json")
_CACHE_TTL = 12 * 3600

_S = None
_BASE = None
_DOM = None
_VER = None
_HOME_HTML = None   # homepage scaricata da _ensure(), riusata da home() (evita di riscaricarla)


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


def _github_dom():
    """Dominio SC dai domains.json mantenuti su GitHub (fonte JSON stabile e auto-aggiornata).
    Prova ogni URL della lista e ritorna il primo dominio valido trovato."""
    for url in GITHUB_DOMAINS:
        try:
            j = requests.get(url, headers=_h(), timeout=10).json()
            full = (j.get("streamingcommunity") or {}).get("full_url") or ""
            d = full.split("//")[-1].split("/")[0].replace("www.", "")
            if d:
                return d
        except Exception:
            continue
    return None


def _estrai_domini(text):
    """Estrae i domini SC-like da un HTML, scartando i falsi positivi (estensioni di file)."""
    out = []
    for d in re.findall(_PAT_DOM, text or "", re.I):
        d = d.lower().strip(".")
        if d.rsplit(".", 1)[-1] in _TLD_JUNK:
            continue
        if d not in out:
            out.append(d)
    return out


def _candidati_dominio():
    """Genera candidati SC in modo LAZY, fonte per fonte in ordine di affidabilità: prima la
    domains.json di GitHub (JSON stabile), poi Startpage(=Google), poi tutte le guide. Chi chiama
    valida e si ferma al PRIMO valido -> se GitHub basta, le guide non vengono nemmeno scaricate
    (efficiente). Se una fonte cambia/sparisce o linka cloni, le successive coprono."""
    visti = set()

    def nuovi(domini):
        for d in domini:
            if d and d not in visti:
                visti.add(d)
                yield d

    gh = _github_dom()
    yield from nuovi([gh] if gh else [])
    yield from nuovi(_estrai_domini(_get(STARTPAGE, {"query": "streamingcommunity", "cat": "web"})))
    for u in GUIDE:
        yield from nuovi(_estrai_domini(_get(u)))


def _e_mirror_sc(d, timeout=8):
    """True SOLO se è il VERO StreamingCommunity, non un clone/dominio morto. Due prove:
    (1) la home ha la `data-page` Inertia (Laravel/Vue) — veloce, 1 richiesta;
    (2) fallback: l'API `/it/search` risponde JSON CON risultati (i cloni danno HTML, 404 o
        `data:[]` vuoto). La (2) regge anche se un domani SC cambiasse frontend (niente Inertia).
    Così si scartano i cloni (es. streaming-community.art/.school: 200 ma senza backend vixcloud)."""
    if not d:
        return False
    try:
        r = requests.get(f"https://{d}/", headers=_h(), timeout=timeout, allow_redirects=True)
        if r.status_code == 200 and "data-page=" in r.text:
            return True
    except Exception:
        pass
    try:
        rs = requests.get(f"https://{d}/it/search", params={"q": "the"},
                          headers=_h({"Accept": "application/json"}), timeout=timeout)
        if "application/json" in rs.headers.get("content-type", ""):
            return len(rs.json().get("data", [])) > 0
    except Exception:
        pass
    return False


def _cache_get(solo_fresco=False):
    """Ultimo dominio noto-funzionante dalla cache. solo_fresco=True lo ritorna solo se scritto
    da meno di _CACHE_TTL (per decidere se provare a cercarne uno più fresco); di default lo
    ritorna a QUALSIASI età (serve da rete di sicurezza: se è ancora vivo, l'app non si rompe)."""
    try:
        with open(_CACHE, encoding="utf-8") as f:
            e = json.load(f)
        dom = e.get("dom")
        if dom and (not solo_fresco or (time.time() - e.get("ts", 0)) < _CACHE_TTL):
            return dom
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


def _override_manuale():
    """Dominio SC forzato a mano: se l'auto-risoluzione sbaglia (le guide linkano cloni/domini
    morti), l'utente mette il dominio corrente in app/dominio_sc.txt e vince su tutto."""
    f = percorsi.override("dominio_sc.txt")
    if not f:
        return None
    try:
        with open(f, encoding="utf-8") as fh:
            d = fh.read().strip()
        return d.replace("https://", "").replace("http://", "").strip("/ ") or None
    except Exception:
        return None


def dominio(forza=False):
    """Dominio del VERO StreamingCommunity, risolto in modo LONGEVO (si auto-ripara). Ordine:
    (1) override manuale `dominio_sc.txt` (se valido, vince su tutto);
    (2) cache FRESCA rivalidata -> apertura istantanea se l'ultimo dominio regge ancora;
    (3) scoperta da molte fonti ridondanti (Startpage + guide), primo mirror SC REALE valido;
    (4) RETE DI SICUREZZA: se la scoperta non trova nulla, si ripiega sull'ultimo dominio
        noto-funzionante (qualsiasi età) se è ANCORA VIVO — così l'app non si rompe mai finché
        un dominio conosciuto funziona, anche se le fonti di scoperta cambiano o falliscono.
    Il buono trovato va in cache. La validazione (`_e_mirror_sc`, backend reale) è il vero giudice,
    quindi non serve indovinare come si scrive l'URL: qualunque candidato vero viene accettato."""
    global _DOM
    if _DOM and not forza:
        return _DOM
    ov = _override_manuale()
    if _e_mirror_sc(ov):                       # override verificato -> vince
        _DOM = ov
        _cache_set(ov)
        return _DOM
    if not forza:
        fresco = _cache_get(solo_fresco=True)
        if fresco and _e_mirror_sc(fresco):    # cache recente ancora viva -> istantaneo
            _DOM = fresco
            return _DOM
    for d in _candidati_dominio():             # cerca il più aggiornato
        if _e_mirror_sc(d):
            _DOM = d
            _cache_set(d)
            return _DOM
    ultimo = _cache_get()                       # scoperta fallita: ripiega sull'ultimo vivo
    if ultimo and _e_mirror_sc(ultimo):
        _DOM = ultimo
        _cache_set(ultimo)
        return _DOM
    _DOM = ov
    return _DOM


def _ensure():
    global _S, _BASE, _VER, _HOME_HTML
    base = dominio()
    if not base:
        return None, None
    if _S is None or _BASE != base:
        _S = requests.Session()
        _S.headers.update(_h())
        try:
            home = _S.get(f"https://{base}/", timeout=15).text
        except Exception:
            return None, None
        _HOME_HTML = home          # la riusa home() invece di riscaricarla
        mm = re.search(r'data-page="([\s\S]+?})"', home)
        try:
            _VER = json.loads(_html.unescape(mm.group(1))).get("version") if mm else None
        except Exception:
            _VER = None
        _BASE = base
    return _S, base


def _poster(t):
    for img in t.get("images", []):
        if img.get("type") == "poster" and img.get("filename"):
            return f"https://cdn.{_BASE}/images/{img['filename']}"
    return None


def _img(t, *tipi):
    """Prima immagine disponibile tra i tipi richiesti (poster/background/cover)."""
    for want in tipi:
        for img in t.get("images", []):
            if img.get("type") == want and img.get("filename"):
                return f"https://cdn.{_BASE}/images/{img['filename']}"
    return None


def home():
    """Righe della homepage SC (del momento / aggiunti di recente / top10) + generi.
    Ritorna (righe, generi) con righe = [(label, [item, ...])] pronte da mostrare."""
    global _HOME_HTML
    s, base = _ensure()
    if not s:
        return [], []
    page = _HOME_HTML            # riusa la homepage scaricata da _ensure()
    _HOME_HTML = None            # consuma: la prossima volta riscarica fresco
    if not page:
        try:
            page = s.get(f"https://{base}/", timeout=15).text
        except Exception:
            return [], []
    m = re.search(r'data-page="([\s\S]+?})"', page)
    if not m:
        return [], []
    try:
        props = json.loads(_html.unescape(m.group(1))).get("props", {})
    except Exception:
        return [], []
    righe = []
    for sl in props.get("sliders", []):
        items = []
        for t in (sl.get("titles") or []):
            items.append({"id": t["id"], "slug": t.get("slug"), "name": t.get("name"),
                          "type": t.get("type"), "poster": _img(t, "poster"),
                          "landscape": _img(t, "background", "cover_mobile", "cover"),
                          "background": _img(t, "background", "cover", "poster"),
                          "logo": _img(t, "logo"),
                          "year": (t.get("last_air_date") or t.get("release_date") or "")[:4],
                          "score": t.get("score"), "seasons": t.get("seasons_count", 0)})
        if items:
            righe.append((sl.get("label") or sl.get("name"), items))
    generi = [{"id": g["id"], "name": g.get("name"), "type": g.get("type")}
              for g in props.get("genres", []) if not g.get("hidden")]
    return righe, generi


def _item(t):
    """Mappa un titolo SC nel formato usato dai caroselli della home."""
    return {"id": t["id"], "slug": t.get("slug"), "name": t.get("name"),
            "type": t.get("type"), "poster": _img(t, "poster"),
            "landscape": _img(t, "background", "cover_mobile", "cover"),
            "background": _img(t, "background", "cover", "poster"),
            "logo": _img(t, "logo"),
            "year": (t.get("last_air_date") or t.get("release_date") or "")[:4],
            "score": t.get("score"), "seasons": t.get("seasons_count", 0)}


def per_genere(genere_id, sort="views", pagine=1):
    """Titoli filtrati per genere via l'endpoint archive (paginator Laravel):
    GET /it/archive?genre[]={id_intero}&sort=views&page=N
    (genre[] vuole l'ID INTERO del genere; sort=views = i piu' popolari).
    Ritorna una lista di item con gli stessi campi di home()."""
    s, base = _ensure()
    if not s:
        return []
    jh = _h({"Accept": "application/json", "X-Requested-With": "XMLHttpRequest"})
    out = []
    for page in range(1, pagine + 1):
        try:
            r = s.get(f"https://{base}/it/archive",
                      params={"genre[]": int(genere_id), "sort": sort, "page": page},
                      headers=jh, timeout=15)
            r.raise_for_status()
            data = r.json().get("data") or []
        except Exception:
            break
        if not data:
            break
        out.extend(_item(t) for t in data)
    return out


def cerca(query):
    """Ricerca SC -> [{id, slug, name, type, poster, score, seasons}]."""
    s, base = _ensure()
    if not s:
        return []
    r = s.get(f"https://{base}/it/search", params={"q": query},
              headers=_h({"Accept": "application/json"}), timeout=15)
    r.raise_for_status()
    out = []
    for t in r.json().get("data", [])[:60]:
        out.append({
            "id": t["id"], "slug": t.get("slug"), "name": t.get("name"),
            "type": t.get("type"), "poster": _poster(t),
            "landscape": _img(t, "background", "cover_mobile", "cover"),
            "year": (t.get("last_air_date") or t.get("release_date") or "")[:4],
            "score": t.get("score"), "seasons": t.get("seasons_count", 0),
        })
    return out


def _full_props(title_id, slug):
    """data-page completa (ha title.seasons)."""
    s, base = _ensure()
    if not s:
        return {}
    r = s.get(f"https://{base}/it/titles/{title_id}-{slug}", timeout=15)
    m = re.search(r'data-page="([\s\S]+?})"', r.text)
    if not m:
        return {}
    try:
        return json.loads(_html.unescape(m.group(1))).get("props", {})
    except Exception:
        return {}


def _season_props(title_id, slug, season):
    """Partial Inertia per gli episodi di una stagione specifica."""
    s, base = _ensure()
    if not s:
        return {}
    ih = _h({"X-Inertia": "true", "X-Inertia-Version": _VER or "", "Accept": "application/json"})
    r = s.get(f"https://{base}/it/titles/{title_id}-{slug}/season-{season}",
              headers=ih, timeout=15)
    try:
        return r.json().get("props", {})
    except Exception:
        return _full_props(title_id, slug)


def stagioni(title_id, slug):
    """Numeri di stagione di una serie (lista vuota per i film)."""
    seasons = (_full_props(title_id, slug).get("title") or {}).get("seasons") or []
    return [s.get("number") for s in seasons if s.get("number")]


def dettaglio(title_id, slug):
    """Dati ricchi del titolo per la pagina dettaglio (trama, backdrop, anno, generi…)."""
    t = (_full_props(title_id, slug).get("title")) or {}
    return {
        "name": t.get("name"), "plot": t.get("plot"), "type": t.get("type"),
        "year": (t.get("release_date") or "")[:4],
        "score": t.get("score"), "runtime": t.get("runtime"), "quality": t.get("quality"),
        "genres": [g.get("name") for g in (t.get("genres") or []) if g.get("name")][:5],
        "backdrop": _img(t, "background", "cover", "poster"),
        "poster": _img(t, "poster"),
        "seasons": [s.get("number") for s in (t.get("seasons") or []) if s.get("number")],
    }


def episodi(title_id, slug, stagione):
    """Episodi di una stagione -> [{id, number, name, plot, duration, image}]."""
    eps = (_season_props(title_id, slug, stagione).get("loadedSeason") or {}).get("episodes") or []
    out = []
    for e in eps:
        img = None
        for im in e.get("images", []):
            if im.get("filename"):
                img = f"https://cdn.{_BASE}/images/{im['filename']}"
        out.append({"id": e["id"], "number": e.get("number"), "name": e.get("name"),
                    "plot": e.get("plot"), "duration": e.get("duration"), "image": img})
    return out


# ─────────────────────────────────────────────────────────────────────────
#  Durate vere
#  I minuti dichiarati da SC nel campo "duration" sono spesso sbagliati, e non
#  di poco: misurato il 2026-09-21 -> Love, Death + Robots dava 21 min per ogni
#  episodio della stagione 1 (in realta' 7-18, "Il dominio dello yogurt" ne dura
#  7), Chernobyl sbagliava di +20 min, Arcane di -9. Breaking Bad invece era
#  giusto: non c'e' modo di sapere in anticipo di chi fidarsi.
#  L'unico dato affidabile e' il flusso stesso. Si misura una volta per episodio
#  e si tiene in cache su disco per sempre: una durata non cambia mai.
# ─────────────────────────────────────────────────────────────────────────
_F_DURATE = percorsi.dato("durate_cache.json")
_DURATE = None
_DURATE_LOCK = threading.RLock()   # RLock: cosi' un futuro annidamento non blocca tutto


def _durate_cache():
    """Il dizionario condiviso delle durate. Il lock non e' pignoleria: la misura gira
    anche in background, e senza di esso due thread potrebbero caricarlo insieme e
    ritrovarsi con due dizionari diversi, perdendo le misure l'uno dell'altro."""
    global _DURATE
    with _DURATE_LOCK:
        if _DURATE is None:
            try:
                with open(_F_DURATE, encoding="utf-8") as f:
                    _DURATE = json.load(f)
            except Exception:
                _DURATE = {}
        return _DURATE


def durata_episodio(title_id, episode_id):
    """Durata vera in minuti di un episodio, misurata sul flusso. None se non riesce."""
    link = m3u8(title_id, episode_id)
    if not link:
        return None
    secondi = vixcloud.durata(link)
    return int(round(secondi / 60.0)) if secondi else None


def durate(title_id, lista_episodi, misura=True, paralleli=6):
    """{episode_id: minuti} per gli episodi dati.

    misura=False -> restituisce solo quello che e' gia' in cache, senza toccare la
    rete: serve dove un ritardo darebbe fastidio (es. all'apertura del player).
    """
    cache = _durate_cache()
    fuori, mancanti = {}, []
    for e in lista_episodi:
        chiave = "%s:%s" % (title_id, e.get("id"))
        if chiave in cache:
            fuori[e.get("id")] = cache[chiave]
        else:
            mancanti.append(e)
    if not (misura and mancanti):
        return fuori
    import concurrent.futures as _cf
    with _cf.ThreadPoolExecutor(max_workers=min(paralleli, len(mancanti))) as ex:
        misurate = list(ex.map(
            lambda e: (e.get("id"), durata_episodio(title_id, e.get("id"))), mancanti))
    with _DURATE_LOCK:
        for eid, minuti in misurate:
            if minuti:
                cache["%s:%s" % (title_id, eid)] = minuti
                fuori[eid] = minuti
        try:
            with open(_F_DURATE, "w", encoding="utf-8") as f:
                json.dump(cache, f)
        except Exception:
            pass
    return fuori


def durate_in_background(title_id, lista_episodi):
    """Riempie la cache senza far aspettare nessuno: la prossima volta i minuti
    mostrati saranno quelli giusti."""
    if not lista_episodi:
        return
    threading.Thread(target=durate, args=(title_id, lista_episodi),
                     kwargs={"paralleli": 4}, daemon=True).start()


def m3u8(title_id, episode_id=None):
    """m3u8 del film (solo title_id) o dell'episodio (title_id + episode_id)."""
    s, base = _ensure()
    if not s:
        return None
    r = s.get(f"https://{base}/it/iframe/{title_id}",
              params=({"episode_id": episode_id} if episode_id else None), timeout=15)
    m = re.search(r'<iframe[^>]+src="([^"]+)"', r.text)
    if not m:
        return None
    return estrai_m3u8(m.group(1).replace("&amp;", "&"), session=s, referer=f"https://{base}/")


_TMDB = {}


def tmdb_id(title_id, slug=None):
    """ID TMDB del titolo (serve alla sorgente alternativa VixSrc, che indicizza per TMDB).
    SC lo espone solo nella scheda completa: si tiene in cache in memoria perche' non cambia mai."""
    chiave = str(title_id)
    if chiave in _TMDB:
        return _TMDB[chiave]
    val = None
    try:
        t = (_full_props(title_id, slug or "") or {}).get("title") or {}
        val = t.get("tmdb_id") or None
    except Exception:
        val = None
    _TMDB[chiave] = val
    return val
