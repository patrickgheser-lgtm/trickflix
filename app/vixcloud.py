"""
TrickFlix - Estrattore m3u8 da un embed vixcloud (backend condiviso di
StreamingCommunity e AnimeUnity). La pagina embed contiene:
  window.masterPlaylist = { url: '...', params: { token, expires } }
L'm3u8 si gioca DIRETTO nel player (hls.js nel Chrome vero, che passa Cloudflare da solo).

⚠️ vixcloud.co e' dietro Cloudflare "managed challenge": una GET con requests prende 403.
curl_cffi impersona il fingerprint TLS di Chrome reale e passa la sfida SENZA aprire un
browser. Fallback a requests se curl_cffi manca (funziona finche' non c'e' Cloudflare).
"""
import re
import requests

try:
    from curl_cffi import requests as _cffi
except Exception:                       # pragma: no cover - se non installato
    _cffi = None

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")


def scarica_pagina(url, referer=None, timeout=20):
    """GET che supera Cloudflare via curl_cffi (impersona Chrome). Ritorna il testo, o
    solleva l'ultima eccezione."""
    if _cffi is not None:
        try:
            # NB: NON impostare lo User-Agent qui — impersonate="chrome" imposta gia' un
            # header-set coerente col fingerprint TLS. Forzare un UA diverso crea un
            # mismatch UA/TLS che Cloudflare rileva -> 403. Passiamo solo il Referer.
            hdr = {"Referer": referer} if referer else {}
            r = _cffi.get(url, headers=hdr, impersonate="chrome", timeout=timeout)
            if r.status_code == 200:
                return r.text
        except Exception:
            pass
    hdr = {"User-Agent": UA}                               # fallback requests
    if referer:
        hdr["Referer"] = referer
    r = requests.get(url, headers=hdr, timeout=timeout)
    r.raise_for_status()
    return r.text


def estrai_m3u8(embed_url, session=None, referer=None):
    """Ritorna l'URL m3u8 master (con token/expires) dall'embed vixcloud, o None."""
    page = scarica_pagina(embed_url, referer=referer)

    mu = re.search(r"window\.masterPlaylist\s*=\s*\{[\s\S]*?url:\s*'([^']+)'", page)
    mp = re.search(r"params:\s*\{([^}]+)\}", page)
    if not (mu and mp):
        return None

    params = mp.group(1)
    tok = re.search(r"'?token'?\s*:\s*'([^']+)'", params)
    exp = re.search(r"'?expires'?\s*:\s*'?(\d+)", params)
    if not (tok and exp):
        return None

    # &h=1 = richiesta FHD/1080p: vixcloud lo ACCETTA solo se canPlayFHD e' true,
    # altrimenti risponde 403 (cambiamento giu 2026) -> aggiungilo solo quando disponibile.
    fhd = re.search(r"window\.canPlayFHD\s*=\s*(true)", page)
    url = mu.group(1)
    sep = "&" if "?" in url else "?"
    out = f"{url}{sep}token={tok.group(1)}&expires={exp.group(1)}"
    if fhd:
        out += "&h=1"
    return out
