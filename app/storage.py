import json
import os
import time

_DIR = os.path.dirname(os.path.abspath(__file__))
FILE_DATI = os.path.join(_DIR, "dati.json")
FILE_POS = os.path.join(_DIR, "posizioni.json")   # minuto raggiunto (continua a guardare)
FILE_PICK = os.path.join(_DIR, "pick.json")        # ultima card cliccata nella home Netflix


def salva_pick(uid):
    """Registra la card cliccata (il player/home è un iframe opaco: comunica via ponte)."""
    tmp = FILE_PICK + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"uid": uid, "t": time.time()}, f)
    os.replace(tmp, FILE_PICK)


def leggi_pick():
    try:
        with open(FILE_PICK, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def leggi_posizioni():
    """Tutte le posizioni salvate: {resume_key: {p, d, t}}."""
    if os.path.exists(FILE_POS):
        try:
            with open(FILE_POS, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def salva_posizione(key, p, d):
    """Salva il minuto 'p' (durata 'd') per la chiave. Scrittura atomica."""
    if not key:
        return
    pos = leggi_posizioni()
    pos[str(key)] = {"p": float(p), "d": float(d), "t": time.time()}
    # tiene leggero: max 200 voci, le più recenti
    if len(pos) > 200:
        ordinate = sorted(pos.items(), key=lambda kv: kv[1].get("t", 0), reverse=True)[:200]
        pos = dict(ordinate)
    tmp = FILE_POS + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(pos, f)
    os.replace(tmp, FILE_POS)


def posizione(key):
    """{p, d, t} per la chiave, oppure None."""
    return leggi_posizioni().get(str(key))

def carica_dati():
    """Carica i dati dal file JSON. Se non esiste, restituisce dizionari vuoti."""
    if os.path.exists(FILE_DATI):
        with open(FILE_DATI, "r", encoding="utf-8") as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                return {"recenti": [], "preferiti": []}
    return {"recenti": [], "preferiti": []}

def salva_dati(dati):
    """Salva il dizionario nel JSON in modo ATOMICO (scrive un .tmp e poi rinomina):
    evita file corrotti/persi se l'app viene chiusa o se OneDrive sincronizza a metà."""
    tmp = FILE_DATI + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(dati, f, indent=4)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, FILE_DATI)

def aggiungi_recente(elemento):
    """Aggiunge un titolo ai visti di recente."""
    dati = carica_dati()
    recenti = dati.get("recenti", [])

    # Se il titolo è già nei recenti, lo rimuove per poterlo rimettere "in cima"
    uid = elemento.get('tmdb_id')
    recenti = [r for r in recenti if r.get('tmdb_id') != uid]
    
    # Aggiunge in coda (che nel nostro app.py viene letto al contrario, quindi per primo)
    recenti.append(elemento)
    
    # Mantiene la cronologia leggera: salva solo gli ultimi 50 visti
    if len(recenti) > 50:
        recenti = recenti[-50:]
        
    dati["recenti"] = recenti
    salva_dati(dati)

def toggle_preferito(elemento):
    """Aggiunge o rimuove un titolo dai preferiti."""
    dati = carica_dati()
    preferiti = dati.get("preferiti", [])
    
    tmdb_id = elemento['tmdb_id']
    
    # Controlla se è già nei preferiti
    if any(p['tmdb_id'] == tmdb_id for p in preferiti):
        # Lo rimuove
        preferiti = [p for p in preferiti if p['tmdb_id'] != tmdb_id]
    else:
        # Lo aggiunge
        preferiti.append(elemento)
        
    dati["preferiti"] = preferiti
    salva_dati(dati)

def is_preferito(tmdb_id):
    """Verifica se un ID è presente nei preferiti."""
    dati = carica_dati()
    preferiti = dati.get("preferiti", [])
    return any(p['tmdb_id'] == tmdb_id for p in preferiti)

# ── preferenze di riproduzione (lingua audio, sottotitoli, qualità) ──────────
# Si ricordano PER SERIE (chiave = uid, es. "sc:12641"), così riaprendo un altro
# episodio parte già con le impostazioni dell'ultima volta. Se per quella serie non
# c'è ancora nulla si usano le ULTIME usate in assoluto ("_ultimo"), così anche la
# prima puntata di una serie nuova parte come l'utente guarda di solito.
# Si salvano valori SEMANTICI (codice lingua, altezza video), non indici: le tracce
# cambiano ordine/numero da un episodio all'altro.
FILE_PREF = os.path.join(_DIR, "preferenze.json")
_ULTIMO = "_ultimo"


def leggi_preferenze():
    try:
        with open(FILE_PREF, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def salva_preferenze(uid, audio=None, sub=None, subname=None, qual=None):
    """Aggiorna le preferenze della serie 'uid' e le 'ultime usate' globali."""
    pref = leggi_preferenze()
    voce = dict(pref.get(str(uid)) or {}) if uid else {}
    for chiave, valore in (("audio", audio), ("sub", sub), ("subname", subname), ("qual", qual)):
        if valore is not None and valore != "":
            voce[chiave] = valore
    if not voce:
        return
    if voce.get("sub") == "off":
        voce["subname"] = ""      # sottotitoli spenti: scordati anche quale traccia era
    voce["t"] = time.time()
    if uid and str(uid) != _ULTIMO:
        pref[str(uid)] = voce
    ultimo = dict(pref.get(_ULTIMO) or {})
    ultimo.update(voce)
    pref[_ULTIMO] = ultimo
    # tiene leggero: max 300 serie, le più recenti (l'ultimo globale resta sempre)
    if len(pref) > 301:
        serie = [(k, v) for k, v in pref.items() if k != _ULTIMO]
        serie.sort(key=lambda kv: kv[1].get("t", 0), reverse=True)
        pref = dict(serie[:300])
        pref[_ULTIMO] = ultimo
    tmp = FILE_PREF + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(pref, f)
    os.replace(tmp, FILE_PREF)


def preferenze(uid=None):
    """Preferenze della serie 'uid'; se non ce ne sono, le ultime usate in assoluto."""
    pref = leggi_preferenze()
    if uid and pref.get(str(uid)):
        return pref[str(uid)]
    return pref.get(_ULTIMO) or {}


# ── richieste che arrivano DAL player (popup episodi / prossimo episodio) ────
# Il player è un iframe a origine opaca: può solo INVIARE (beacon-immagine verso il
# ponte), non può fare fetch né caricare script da localhost (Private Network Access).
# Quindi deposita qui la richiesta e l'app, che fa polling, la esegue.
FILE_VAI = os.path.join(_DIR, "vai.json")


def salva_vai(ep_id, stagione=None, numero=None):
    if not ep_id:
        return
    tmp = FILE_VAI + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"ep": str(ep_id), "s": stagione, "n": numero, "t": time.time()}, f)
    os.replace(tmp, FILE_VAI)


def leggi_vai():
    try:
        with open(FILE_VAI, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


# ── azioni richieste dal player (download / cast) ────────────────────────────
# Stesso principio di salva_vai(): l'iframe puo' solo mandare un beacon, l'app fa polling.
FILE_AZIONE = os.path.join(_DIR, "azione.json")


def salva_azione(nome, dato=""):
    if not nome:
        return
    tmp = FILE_AZIONE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"a": nome, "d": dato or "", "t": time.time()}, f)
    os.replace(tmp, FILE_AZIONE)


def leggi_azione():
    try:
        with open(FILE_AZIONE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None
