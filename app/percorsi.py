"""Dove TrickFlix tiene il CODICE e dove tiene i DATI.

Fino alla 3.9.2 erano la stessa cartella: l'app scriveva accanto ai propri .py.
Su Windows va benissimo (l'installer la mette in %LOCALAPPDATA%, che e' scrivibile),
ma su macOS un'app vive in /Applications e **non deve scrivere dentro il proprio
bundle**: servirebbero i permessi di amministratore, si invaliderebbe la firma, e
macOS puo' perfino eseguirla da una copia in sola lettura (App Translocation).

Quindi:
  - macOS              -> i dati vanno in ~/Library/Application Support/TrickFlix
  - Windows / Linux    -> restano accanto al codice, ESATTAMENTE come prima

Su Windows non si cambia nulla di proposito: spostare i dati adesso lascerebbe
orfani la cronologia e i download di chi l'app ce l'ha gia' installata.
"""

import os
import sys

# Dove stanno i .py. Su macOS e' dentro il bundle: da considerare in sola lettura.
CODICE = os.path.dirname(os.path.abspath(__file__))


def _cartella_dati():
    if sys.platform != "darwin":
        return CODICE

    # Installazione "a cartella" gia' avviata su Mac (quelle distribuite prima
    # del .dmg): i dati stanno accanto al codice. Spostare il riferimento adesso
    # farebbe SPARIRE cronologia e download a chi ce l'ha gia'. Se li troviamo
    # li', si resta li'.
    if os.path.isfile(os.path.join(CODICE, "dati.json")):
        return CODICE

    # App dentro un bundle in /Applications: non si scrive nel bundle.
    d = os.path.expanduser("~/Library/Application Support/TrickFlix")
    try:
        os.makedirs(d, exist_ok=True)
        return d
    except Exception:
        return CODICE          # meglio funzionare male che non partire


DATI = _cartella_dati()


def dato(*pezzi):
    """Percorso di un file di dati (cronologia, cache, download...)."""
    return os.path.join(DATI, *pezzi)


def codice(*pezzi):
    """Percorso di un file che fa parte del programma (sola lettura su macOS)."""
    return os.path.join(CODICE, *pezzi)


def override(nome):
    """File messo a mano dall'utente (es. dominio_sc.txt): si cerca prima tra i
    dati, poi accanto al codice. Cosi' chi ne aveva gia' uno su Windows se lo
    ritrova, e su macOS se ne puo' creare uno senza toccare il bundle."""
    for p in (dato(nome), codice(nome)):
        if os.path.isfile(p):
            return p
    return None
