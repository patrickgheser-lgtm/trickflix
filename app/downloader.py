"""
TrickFlix - Download di un titolo come PACCHETTO HLS LOCALE (come fanno i servizi
di streaming per l'offline: tracce separate, niente mux fragile).

Per ogni download crea una cartella con:
  video.ts  + video.m3u8        (segmenti video concatenati, indicizzati a byte-range)
  audio_N.ts + audio_N.m3u8     (una per ogni traccia audio: italiano, originale, ...)
  sub_N.vtt + sub_N.m3u8        (sottotitoli)
  master.m3u8                   (lega tutto: hls.js lo riproduce con i menu tracce)

Affidabilita':
  - vixcloud da' HTTP 503 oltre ~16 connessioni -> max 16 worker;
  - retry con backoff sui segmenti; se un segmento NON si scarica si SOLLEVA
    errore (mai produrre un file bucato -> niente frame mancanti/audio muto);
  - i segmenti sono TS cifrati AES-128 -> decifrati al volo (pycryptodome).
Si puo' annullare (cancel_event). Mostra velocita' e tempo rimanente.
"""
import os
import re
import time
import math
import shutil
import threading
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from Crypto.Cipher import AES

try:
    from curl_cffi import requests as _cffi
except Exception:                       # pragma: no cover - se non installato
    _cffi = None

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

MAX_WORKERS = 16   # oltre, vixcloud risponde 503


class DownloadAnnullato(Exception):
    """L'utente ha annullato."""


class DownloadError(Exception):
    """Download fallito (es. un segmento non scaricabile): niente file bucati."""


def ffmpeg_exe():
    try:
        import imageio_ffmpeg
        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if exe and os.path.exists(exe):
            return exe
    except Exception:
        pass
    return shutil.which("ffmpeg") or "ffmpeg"


class _Sessione:
    """Sessione HTTP thread-safe per il download. vixcloud.co è dietro Cloudflare
    "managed challenge": serve curl_cffi (impersona il TLS di Chrome reale) per non
    prendere 403 su playlist/segmenti. Le sessioni curl_cffi NON si condividono tra
    thread -> ognuno ha la sua (threading.local). Fallback a requests se curl_cffi manca."""

    def __init__(self):
        self._local = threading.local()

    def _s(self):
        s = getattr(self._local, "s", None)
        if s is None:
            if _cffi is not None:
                # NON impostare User-Agent: impersonate imposta un header-set coerente col
                # fingerprint TLS; forzare un UA diverso fa scattare Cloudflare (mismatch).
                s = _cffi.Session(impersonate="chrome")
            else:
                s = requests.Session()
                ad = requests.adapters.HTTPAdapter(max_retries=0)
                s.mount("http://", ad)
                s.mount("https://", ad)
                s.headers.update({"User-Agent": UA})
            self._local.s = s
        return s

    def get(self, url, **kw):
        return self._s().get(url, **kw)


def _session(workers):
    return _Sessione()


def _abs(base, u):
    return urllib.parse.urljoin(base, u)


def _parse_master(text, base):
    """Ritorna (audios, subs, variants)."""
    audios, subs, variants = [], [], []
    lines = text.splitlines()
    for i, l in enumerate(lines):
        if l.startswith("#EXT-X-MEDIA") and "TYPE=AUDIO" in l:
            lang = re.search(r'LANGUAGE="([^"]*)"', l)
            name = re.search(r'NAME="([^"]*)"', l)
            uri = re.search(r'URI="([^"]*)"', l)
            if uri:
                audios.append({"lang": lang.group(1) if lang else "", "name": name.group(1) if name else "",
                               "uri": _abs(base, uri.group(1)), "default": "DEFAULT=YES" in l})
        elif l.startswith("#EXT-X-MEDIA") and "TYPE=SUBTITLES" in l:
            lang = re.search(r'LANGUAGE="([^"]*)"', l)
            name = re.search(r'NAME="([^"]*)"', l)
            uri = re.search(r'URI="([^"]*)"', l)
            if uri:
                subs.append({"lang": lang.group(1) if lang else "", "name": name.group(1) if name else "",
                             "uri": _abs(base, uri.group(1)),
                             "forced": "forced" in ((lang.group(1).lower() if lang else ""))})
        elif l.startswith("#EXT-X-STREAM-INF"):
            res = re.search(r'RESOLUTION=\d+x(\d+)', l)
            bw = re.search(r'BANDWIDTH=(\d+)', l)
            cod = re.search(r'CODECS="([^"]*)"', l)
            uri = lines[i + 1].strip() if i + 1 < len(lines) else ""
            if uri and not uri.startswith("#"):
                variants.append({"height": int(res.group(1)) if res else 0,
                                 "bandwidth": int(bw.group(1)) if bw else 2000000,
                                 "codecs": cod.group(1) if cod else "", "uri": _abs(base, uri)})
    return audios, subs, variants


def _pick_variant(variants, height):
    if not variants:
        return None
    exact = [v for v in variants if v["height"] == height]
    if exact:
        return exact[0]
    le = [v for v in variants if v["height"] <= height]
    if le:
        return max(le, key=lambda v: v["height"])
    return min(variants, key=lambda v: v["height"])


def _ord_audio(audios):
    return sorted(audios, key=lambda a: 0 if (a["lang"] or "").lower().startswith("it") else 1)


def _lang3(lang):
    L = (lang or "").lower().replace("forced-", "")
    return {"it": "ita", "ita": "ita", "en": "eng", "eng": "eng", "ja": "jpn", "jpn": "jpn",
            "es": "spa", "fr": "fra", "de": "deu"}.get(L, (L[:3] or "und"))


def _etichetta(lang, name, forced=False):
    L = (lang or "").lower()
    if L.startswith("it"):
        base = "Italiano"
    elif L.startswith("en"):
        base = "Inglese (originale)"
    elif L.startswith("ja"):
        base = "Giapponese (originale)"
    else:
        base = name or lang or "Traccia"
    if forced or "forced" in L:
        base += " (forzati)"
    elif "[CC]" in (name or ""):
        base += " (CC)"
    return base


def _parse_media(session, playlist_url):
    """(segments, durations, key|None, iv|None, seq_start)."""
    r = session.get(playlist_url, timeout=30)
    r.raise_for_status()
    text = r.text
    key_bytes, iv_bytes, seq = None, None, 0
    mseq = re.search(r"#EXT-X-MEDIA-SEQUENCE:(\d+)", text)
    if mseq:
        seq = int(mseq.group(1))
    mkey = re.search(r'#EXT-X-KEY:[^\n]*METHOD=AES-128[^\n]*', text)
    if mkey:
        ku = re.search(r'URI="([^"]*)"', mkey.group(0))
        iv = re.search(r'IV=0x([0-9A-Fa-f]+)', mkey.group(0))
        if ku:
            key_bytes = session.get(_abs(playlist_url, ku.group(1)), timeout=30).content
        if iv:
            iv_bytes = bytes.fromhex(iv.group(1))
    segs, durs, pend = [], [], 4.0
    for l in text.splitlines():
        if l.startswith("#EXTINF:"):
            m = re.search(r'#EXTINF:([\d.]+)', l)
            pend = float(m.group(1)) if m else 4.0
        elif l.strip() and not l.startswith("#"):
            segs.append(_abs(playlist_url, l.strip()))
            durs.append(pend)
            pend = 4.0
    return segs, durs, key_bytes, iv_bytes, seq


def _unpad(data):
    if not data:
        return data
    p = data[-1]
    if 1 <= p <= 16 and len(data) >= p:
        return data[:-p]
    return data


def _ck(cancel):
    if cancel is not None and cancel.is_set():
        raise DownloadAnnullato()


def _fetch_raw(session, url, cancel, attempts=7):
    """Scarica un segmento con retry/backoff. Solleva DownloadError se non ce la fa."""
    for a in range(attempts):
        _ck(cancel)
        try:
            r = session.get(url, timeout=60)
            if r.status_code == 200 and r.content:
                return r.content
        except Exception:
            pass
        time.sleep(min(2.5, 0.3 * (a + 1)))
    raise DownloadError("segmento non scaricabile dopo %d tentativi" % attempts)


def _download_track(session, segs, durs, key, iv, seq, dest_ts, parts_dir, workers, on_seg, cancel):
    """Scarica i segmenti (decifra), li concatena in dest_ts; ritorna i byte-range
    [(length, duration, offset)] per il media playlist."""
    n = len(segs)
    os.makedirs(parts_dir, exist_ok=True)
    sizes = [0] * n

    def fetch(i):
        data = _fetch_raw(session, segs[i], cancel)
        if key:
            seg_iv = iv if iv is not None else (seq + i).to_bytes(16, "big")
            try:
                data = _unpad(AES.new(key, AES.MODE_CBC, seg_iv).decrypt(data))
            except Exception:
                pass
        with open(os.path.join(parts_dir, "p%06d" % i), "wb") as f:
            f.write(data)
        return i, len(data)

    ex = ThreadPoolExecutor(max_workers=min(workers, MAX_WORKERS))
    try:
        futs = [ex.submit(fetch, i) for i in range(n)]
        for fut in as_completed(futs):
            if cancel is not None and cancel.is_set():
                ex.shutdown(wait=False, cancel_futures=True)
                raise DownloadAnnullato()
            i, sz = fut.result()   # propaga DownloadError -> niente file bucato
            sizes[i] = sz
            if on_seg:
                on_seg(sz)
    finally:
        ex.shutdown(wait=False, cancel_futures=True)

    ranges, off = [], 0
    with open(dest_ts, "wb") as out:
        for i in range(n):
            p = os.path.join(parts_dir, "p%06d" % i)
            with open(p, "rb") as f:
                shutil.copyfileobj(f, out)
            os.remove(p)
            ranges.append((sizes[i], durs[i] if i < len(durs) else 4.0, off))
            off += sizes[i]
    return ranges


def _scarica_vtt(session, sub_playlist_url, dest_vtt):
    try:
        segs = _parse_media(session, sub_playlist_url)[0]
        if not segs:
            return False
        with open(dest_vtt, "wb") as out:
            for u in segs:
                rr = session.get(u, timeout=30)
                if rr.status_code == 200:
                    out.write(rr.content)
        return os.path.getsize(dest_vtt) > 0
    except Exception:
        return False


def _w(path, lines):
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def _media_m3u8(path, ts_name, ranges, target):
    out = ["#EXTM3U", "#EXT-X-VERSION:4", "#EXT-X-PLAYLIST-TYPE:VOD",
           "#EXT-X-TARGETDURATION:%d" % max(1, int(math.ceil(target)))]
    for (ln, dur, off) in ranges:
        out.append("#EXTINF:%.3f," % dur)
        out.append("#EXT-X-BYTERANGE:%d@%d" % (ln, off))
        out.append(ts_name)
    out.append("#EXT-X-ENDLIST")
    _w(path, out)


def _sub_m3u8(path, vtt_name, total):
    _w(path, ["#EXTM3U", "#EXT-X-VERSION:4", "#EXT-X-PLAYLIST-TYPE:VOD",
              "#EXT-X-TARGETDURATION:%d" % max(1, int(math.ceil(total))),
              "#EXTINF:%.3f," % total, vtt_name, "#EXT-X-ENDLIST"])


def _master_m3u8(path, bandwidth, codecs, audio_infos, sub_infos):
    out = ["#EXTM3U", "#EXT-X-VERSION:4"]
    for i, a in enumerate(audio_infos):
        out.append('#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="aud",NAME="%s",LANGUAGE="%s",DEFAULT=%s,AUTOSELECT=YES,URI="%s"'
                   % (a["label"], a["lang3"], "YES" if i == 0 else "NO", a["m3u8"]))
    for s in sub_infos:
        out.append('#EXT-X-MEDIA:TYPE=SUBTITLES,GROUP-ID="sub",NAME="%s",LANGUAGE="%s",DEFAULT=NO,AUTOSELECT=YES,FORCED=NO,URI="%s"'
                   % (s["label"], s["lang3"], s["m3u8"]))
    inf = "#EXT-X-STREAM-INF:BANDWIDTH=%d" % bandwidth
    if codecs:
        inf += ',CODECS="%s"' % codecs
    if audio_infos:
        inf += ',AUDIO="aud"'
    if sub_infos:
        inf += ',SUBTITLES="sub"'
    out.append(inf)
    out.append("video.m3u8")
    _w(path, out)


def _fmt_eta(sec):
    sec = int(max(0, sec))
    h, m, s = sec // 3600, (sec % 3600) // 60, sec % 60
    if h:
        return "%dh %dm" % (h, m)
    if m:
        return "%dm %02ds" % (m, s)
    return "%ds" % s


def scarica(master_url, dest_dir, height=1080, workers=MAX_WORKERS, progress_cb=None,
            cancel_event=None, tutte_le_tracce=True, max_seg=None):
    """
    Scarica il titolo come pacchetto HLS locale nella cartella dest_dir.
    Ritorna il nome del manifest ('master.m3u8'). Solleva DownloadError/DownloadAnnullato.
    """
    workers = min(workers, MAX_WORKERS)
    session = _session(workers)
    r = session.get(master_url, timeout=30)
    r.raise_for_status()
    audios, subs, variants = _parse_master(r.text, master_url)
    var = _pick_variant(variants, height)
    if not var:
        raise DownloadError("Nessuna traccia video nel manifest.")
    audios = _ord_audio(audios)
    if not tutte_le_tracce:
        audios = audios[:1] if audios else []
        subs = []

    if progress_cb:
        progress_cb(0.01, "Leggo le playlist…")
    vsegs, vdur, vkey, viv, vseq = _parse_media(session, var["uri"])
    audio_meta = []
    for a in audios:
        segs, dur, key, iv, seq = _parse_media(session, a["uri"])
        audio_meta.append([a, segs, dur, key, iv, seq])
    if max_seg:
        vsegs, vdur = vsegs[:max_seg], vdur[:max_seg]
        for am in audio_meta:
            am[1], am[2] = am[1][:max_seg], am[2][:max_seg]

    total = len(vsegs) + sum(len(am[1]) for am in audio_meta)
    state = {"done": 0, "bytes": 0, "t0": time.time()}

    def on_seg(nb):
        state["done"] += 1
        state["bytes"] += nb
        el = max(0.001, time.time() - state["t0"])
        frac = state["done"] / total if total else 0
        eta = (total - state["done"]) * (el / state["done"]) if state["done"] else 0
        if progress_cb:
            progress_cb(min(0.97, 0.02 + frac * 0.95),
                        "%d%%  ·  %.1f MB/s  ·  resta %s" % (int(frac * 100), state["bytes"] / el / 1e6, _fmt_eta(eta)))

    os.makedirs(dest_dir, exist_ok=True)
    parts = os.path.join(dest_dir, "_parts")
    try:
        # video
        vr = _download_track(session, vsegs, vdur, vkey, viv, vseq,
                             os.path.join(dest_dir, "video.ts"), os.path.join(parts, "v"),
                             workers, on_seg, cancel_event)
        _media_m3u8(os.path.join(dest_dir, "video.m3u8"), "video.ts", vr,
                    max((d for (_, d, _) in vr), default=6))
        total_dur = sum(d for (_, d, _) in vr) or 6
        # audio
        audio_infos = []
        for idx, (a, segs, dur, key, iv, seq) in enumerate(audio_meta):
            _ck(cancel_event)
            ar = _download_track(session, segs, dur, key, iv, seq,
                                 os.path.join(dest_dir, "audio_%d.ts" % idx), os.path.join(parts, "a%d" % idx),
                                 workers, on_seg, cancel_event)
            _media_m3u8(os.path.join(dest_dir, "audio_%d.m3u8" % idx), "audio_%d.ts" % idx, ar,
                        max((d for (_, d, _) in ar), default=6))
            audio_infos.append({"label": _etichetta(a["lang"], a["name"]), "lang3": _lang3(a["lang"]),
                                "m3u8": "audio_%d.m3u8" % idx})
        # sottotitoli
        sub_infos = []
        if subs:
            if progress_cb:
                progress_cb(0.98, "Scarico i sottotitoli…")
            for j, s in enumerate(subs):
                _ck(cancel_event)
                if _scarica_vtt(session, s["uri"], os.path.join(dest_dir, "sub_%d.vtt" % j)):
                    _sub_m3u8(os.path.join(dest_dir, "sub_%d.m3u8" % j), "sub_%d.vtt" % j, total_dur)
                    sub_infos.append({"label": _etichetta(s["lang"], s["name"], s.get("forced")),
                                      "lang3": _lang3(s["lang"]), "m3u8": "sub_%d.m3u8" % j})
        # master
        _master_m3u8(os.path.join(dest_dir, "master.m3u8"), var.get("bandwidth", 2000000),
                     var.get("codecs", ""), audio_infos, sub_infos)
        if progress_cb:
            progress_cb(1.0, "Completato")
        return "master.m3u8"
    finally:
        shutil.rmtree(parts, ignore_errors=True)
