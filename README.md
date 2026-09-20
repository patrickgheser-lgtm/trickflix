# TrickFlix — sorgente degli aggiornamenti

Questo repo è la **fonte da cui TrickFlix si aggiorna da sola**. Non è un installatore:
per la prima installazione serve la cartella completa (con gli avviatori e le icone).

## Com'è fatto

- **`aggiornamento.json`** — il manifesto: versione corrente, note di rilascio e, per ogni
  file, il suo `sha256` e la dimensione.
- **`app/`**, **`TrickFlix.bat`**, **`TrickFlix.command`**, **`crea_app_macos.command`** — i
  file di programma nella stessa posizione in cui stanno nell'installazione.

## Come lo usa l'app

All'avvio (in background, una volta al giorno) l'app legge `aggiornamento.json`. Se la
versione è più alta di quella in `app/versione.py`, mostra un popup con le novità. Se
l'utente accetta, scarica **solo i file il cui `sha256` è diverso** da quello che ha su
disco, verifica ciascuno, tiene una copia di quelli che sostituisce e poi si riavvia.

Dati dell'utente — video scaricati, cronologia, preferenze, ambiente Python — non vengono
mai toccati: l'aggiornamento riguarda esclusivamente il codice.

## Per pubblicare una versione

Dalla cartella di lavoro del progetto:

```
python strumenti/pubblica.py --versione 3.9.1 --note "Cosa cambia" --repo <questa cartella> --push
```
