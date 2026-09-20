"""
TrickFlix - casting su Chromecast/Google TV (pychromecast, lato Python).

Il player vive in un iframe a ORIGINE OPACA: il Google Cast SDK JavaScript non si
carica lì (serve un'origine non-opaca). Quindi NON castiamo dal browser ma dal backend:
pychromecast scopre i Chromecast in rete e dice alla TV di scaricare DIRETTAMENTE l'm3u8
vixcloud (pubblico, CORS *, H.264/AAC -> ok per il default media receiver). Niente iframe.

Limite: i video OFFLINE sono serviti dal ponte su 127.0.0.1, non raggiungibile dalla TV
-> il casting è solo per lo streaming ONLINE.

Le connessioni vivono in variabili globali del modulo (persistono tra i rerun di Streamlit,
stesso processo). zeroconf/browser di discovery viene fermato e riavviato ad ogni ricerca.
"""
import time
import threading

try:
    import pychromecast
    from pychromecast.controllers.media import STREAM_TYPE_BUFFERED
    DISPONIBILE = True
except Exception:
    DISPONIBILE = False

_lock = threading.Lock()
_browser = None
_casts = {}        # nome dispositivo -> oggetto Chromecast
_attivo = None     # nome del dispositivo su cui stiamo trasmettendo


def _stop_browser():
    global _browser
    if _browser is not None:
        try:
            pychromecast.discovery.stop_discovery(_browser)
        except Exception:
            pass
        _browser = None


def scopri(timeout=6):
    """Scopre i Chromecast nella rete locale. Ritorna la lista (ordinata) dei nomi (può essere vuota)."""
    global _browser, _casts
    if not DISPONIBILE:
        return []
    with _lock:
        _stop_browser()
        try:
            casts, browser = pychromecast.get_chromecasts(timeout=timeout)
        except Exception:
            return []
        _browser = browser
        _casts = {c.name: c for c in casts}
        return sorted(_casts.keys())


_ultimi = []          # ultimi dispositivi trovati (per il pannello dentro il player)
_ultimo_scan = 0.0
_scan_in_corso = False


def scopri_in_background(eta_max=180):
    """Avvia la ricerca in un THREAD, se serve. Il pannello cast vive dentro il player,
    che e' un iframe a origine opaca: la lista dev'essere gia' pronta al momento del
    render (non puo' chiederla dopo). La ricerca costa ~6s, quindi non va fatta in linea."""
    global _scan_in_corso
    if not DISPONIBILE or _scan_in_corso:
        return
    if _ultimi and (time.time() - _ultimo_scan) < eta_max:
        return                                  # lista recente: va bene cosi'
    _scan_in_corso = True

    def run():
        global _ultimi, _ultimo_scan, _scan_in_corso
        try:
            _ultimi = scopri()
        except Exception:
            pass
        finally:
            _ultimo_scan = time.time()
            _scan_in_corso = False

    threading.Thread(target=run, daemon=True).start()


def dispositivi():
    """Ultima lista nota di dispositivi (puo' essere vuota)."""
    return list(_ultimi)


def ricerca_in_corso():
    return _scan_in_corso


def trasmetti(nome, url, titolo="", start=0.0):
    """Avvia la riproduzione dell'm3u8 sul Chromecast scelto. Ritorna (ok: bool, messaggio: str)."""
    if not DISPONIBILE:
        return False, "Modulo casting non disponibile (pychromecast mancante)."
    cast = _casts.get(nome)
    if cast is None:
        return False, "Dispositivo non trovato: rifai la ricerca."
    global _attivo
    try:
        cast.wait(timeout=12)
        mc = cast.media_controller
        mc.play_media(url, "application/x-mpegurl", title=titolo or None,
                      stream_type=STREAM_TYPE_BUFFERED, current_time=float(start or 0))
        mc.block_until_active(timeout=12)
        _attivo = nome
        return True, f"In riproduzione su «{nome}»."
    except Exception as e:
        return False, f"Errore durante il casting: {e}"


def _mc():
    if _attivo and _attivo in _casts:
        try:
            return _casts[_attivo].media_controller
        except Exception:
            return None
    return None


def pausa():
    mc = _mc()
    if mc:
        try:
            mc.pause()
        except Exception:
            pass


def riprendi():
    mc = _mc()
    if mc:
        try:
            mc.play()
        except Exception:
            pass


def ferma():
    """Ferma la riproduzione sul dispositivo attivo e azzera lo stato."""
    global _attivo
    mc = _mc()
    if mc:
        try:
            mc.stop()
        except Exception:
            pass
    _attivo = None


def attivo():
    """Nome del dispositivo su cui si sta trasmettendo, o None."""
    return _attivo
