# TrickFlix — Guida

## Cosa serve
- **Niente.** Nemmeno Python: se manca (o se la versione installata non va bene per le
  librerie) gli avviatori **scaricano da soli un Python dedicato** dentro
  `app/python-portable/` — ~44 MB, una volta sola. Non installa niente nel sistema, non
  chiede la password e non tocca il Python che usi per altro; per rimuoverlo basta
  cancellare quella cartella.
  - **Windows**: `TrickFlix.bat`
  - **macOS**: `TrickFlix.command`
- Un browser (Chrome consigliato). **Niente estensioni, niente ffmpeg da installare a mano.**

## Come si usa

### Windows
1. Doppio click su **`TrickFlix.bat`**.
   - La prima volta crea l'ambiente e installa tutto da solo (qualche minuto). Se sul PC
     non c'è Python — o c'è una versione con cui le librerie non si installano — se lo
     scarica da solo e prosegue: non devi fare niente.
   - Poi apre l'app e si chiude il terminale. Gli avvii successivi sono immediati (~5s).
   - Se l'ambiente è rotto (es. hai copiato la cartella da un altro PC) lo rifà da zero.

### macOS

**Modo immediato (funziona sempre, niente blocchi):** apri il **Terminale**, scrivi `bash ` (con lo spazio), **trascina** `TrickFlix.command` nella finestra e premi **Invio**. Uno script lanciato così non viene bloccato da Gatekeeper e non serve renderlo eseguibile. La prima volta installa tutto; poi apre l'app.

**Modo "doppio click" (consigliato, da preparare una volta):** generi un vero `TrickFlix.app`.
1. **Una volta sola**, crea l'app: apri il **Terminale**, scrivi `bash `, **trascina** `crea_app_macos.command` dentro, **Invio**. (NON fare doppio click su `crea_app_macos.command`: è lo script che *crea* l'app, e Gatekeeper bloccherebbe il doppio click.) Crea `TrickFlix.app` (vero `.app` via `osacompile`, firma ad-hoc).
2. Poi fai **doppio click su `TrickFlix.app`**. La **primissima volta** macOS dirà che non può verificarlo → **Impostazioni di sistema → Privacy e sicurezza → "Apri comunque"** (UNA volta sola per Mac). Dalla volta dopo si apre diretto.
   - L'app, una volta autorizzata, **toglie da sola la quarantena** ai file → niente più Terminale.
   - Lo script può anche creare un **`TrickFlix.dmg`** per distribuire ad altri.

> Nota: senza un account Apple Developer a pagamento, l'unico passaggio inevitabile è quel singolo **"Apri comunque"** alla primissima apertura — è il comportamento standard di macOS per le app non firmate da uno sviluppatore registrato.

### Poi (uguale su Win e Mac)
1b. La **home** è in stile Netflix: hero in alto + caroselli a **card orizzontali** ("I titoli del momento / Aggiunti di recente / Top 10") e la riga **Continua a guardare** con la **barra del minuto**. Clicca una copertina → si apre la **scheda** (banner + trama; per le serie/anime l'**elenco episodi con anteprima, durata e trama**). Schede in alto: **🏠 Home · 🔍 Cerca · ⭐ Preferiti · 📥 Download**.
1c. **Senza connessione** l'app passa da sola in **modalità offline** (mostra solo i video scaricati) e torna online appena la rete c'è.
2. **Cerca** un titolo: la ricerca è **unica** e trova insieme **film, serie e anime** (puoi poi filtrare per tipo). Premi **🍿 Apri**. Tanti risultati? **"Carica altri risultati"**.
3. **Film**: "Guarda ora". **Serie/Anime**: scegli stagione/episodio → ▶.
4. Parte il player. **Tutti i comandi sono dentro al player**, in basso a destra:
   **⏭ prossimo episodio · ☰ episodi · ⬇ scarica · 📺 trasmetti · 💬 audio e sottotitoli · ⚙ qualità e velocità · ⧉ picture-in-picture · ⛶ schermo intero**.
   A sinistra play/pausa, ±10s e volume. Funzionano anche le scorciatoie da tastiera (k, j, l, m, f).
5. **☰ Episodi** (nel player): apre una finestra **stile Netflix sopra al video, senza interrompere la visione**, con gli episodi della stagione. La **freccia in alto a sinistra** porta alla scelta della stagione. Clicchi un episodio e parte. **⏭** salta direttamente al successivo.
6. **⬇ Scarica** (nel player): **un click e basta** — scarica da solo alla **massima qualità disponibile**, con **tutte le tracce audio e i sottotitoli** (formato HLS, come fanno i servizi di streaming per l'offline). Va in background: stato, velocità, tempo rimanente e **annullamento** sono in **Home → 📥 Download**.
7. **Le tue scelte vengono ricordate.** Lingua audio, sottotitoli e qualità restano impostati **per quella serie**: al prossimo episodio li ritrovi già come li avevi lasciati (e su un titolo nuovo vale l'ultima impostazione usata). Se una traccia non esiste su quell'episodio, viene saltata **solo quella**: le altre preferenze restano.
8. **Home → 📥 Download**: i video **Scaricati** si **guardano offline** dentro l'app — con **audio e sottotitoli selezionabili** come online — oppure si **eliminano** 🗑.
9. **▶ Continua a guardare** (riga scorribile in home, stile Netflix): riprende l'ultimo titolo visto dall'**episodio** e dal **minuto** giusti, con barra di avanzamento.
10. **Si aggiorna da sola.** All'avvio controlla in background se c'è una versione nuova (una volta al giorno, senza rallentare l'apertura). Se c'è, compare un popup con le novità: premi **Aggiorna ora** e l'app scarica i file cambiati, li installa e si riavvia. **I video scaricati, la cronologia e le preferenze non vengono toccati** — cambia solo il programma. In fondo alla home trovi la versione installata e **Cerca aggiornamenti** per controllare subito.
11. **📺 Trasmetti** (nel player, solo streaming online): apre un banner con i **Chromecast/Google TV** trovati sulla rete; scegli il dispositivo e la TV riproduce lo stream (riprende dal minuto salvato). *Nota: metti in pausa a mano il player nel browser; la TV dev'essere sulla stessa rete Wi‑Fi. Se la lista è vuota, accendi la TV e usa "Cerca di nuovo".*

## Come funziona (in breve)
- I film/serie vengono da **StreamingCommunity**, gli anime da **AnimeUnity** (siti italiani, doppiaggio + originale).
- L'app ottiene il flusso video **direttamente via API** (niente estensione, niente cattura dal browser).
- I domini dei siti, che cambiano spesso, vengono **risolti da soli**: l'app li cerca da più fonti
  indipendenti, verifica che il sito trovato sia davvero quello giusto e, se la ricerca fallisce,
  ripiega sull'ultimo dominio ancora vivo. Non c'è niente da aggiornare a mano.
- Gli **aggiornamenti** arrivano da un repo pubblico su GitHub: l'app legge un piccolo file
  che elenca i file dell'ultima versione con la loro impronta (sha256), scarica **solo quelli
  diversi da ciò che hai**, li verifica uno per uno e li installa tutti insieme o nessuno.
  Prima di sostituirli ne tiene una copia in `app/.backup/`.
- Per film e serie c'è anche una **seconda sorgente automatica** (VixSrc): se la principale non
  risponde, l'app ci passa da sola senza che te ne accorga.
- Il player è una **skin Netflix custom su hls.js** (audio IT/originale, qualità 480/720/1080, sottotitoli, popup episodi, download, casting, scorciatoie tastiera, schermo intero), con audio italiano selezionato in automatico e le preferenze ricordate per serie.
- Il **download** decifra i segmenti e li unisce con **ffmpeg "portatile"** scaricato via pip (`imageio-ffmpeg`): niente installazioni di sistema.

## Da mandare ai colleghi
Copia la cartella (senza `venv`, si rigenera). Istruzione unica:
- **Windows**: "apri `TrickFlix.bat`, la prima volta aspetta che finisca, poi usala."
- **Mac**: "tasto destro su `TrickFlix.app` → Apri (solo la prima volta), aspetta, poi usala." (l'app va generata una volta con `crea_app_macos.command`, vedi sopra.)
Non devono installare estensioni né ffmpeg: solo Python (a cui pensano gli avviatori).

## Se qualcosa non va
- Nessun risultato in ricerca → controlla l'ortografia (la ricerca copre già film, serie e anime).
- Un titolo non parte → riprova (token rinnovato) o prova un altro episodio.
- Log tecnico dell'avvio in `app_log.txt`.

## Struttura
La cartella ha in vista **solo gli avviatori**; tutto il resto è dentro `app/`.
```
TrickFlix.bat            ⭐ avvio su Windows (entra in app/ e lancia)
TrickFlix.command        ⭐ avvio su macOS (entra in app/ e lancia)
crea_app_macos.command   genera TrickFlix.app (.app firmato ad-hoc + .dmg) — una volta sul Mac
TrickFlix.app            (creato dal comando sopra) ⭐ avvio macOS a doppio click
app/                     TUTTO il resto del programma:
  launcher.py            avvia server + apre l'app (Win/Mac/Linux)
  app.py                 interfaccia (ricerca → dettagli → player)
  streamingcommunity.py  film/serie (API diretta, vixcloud)
  animeunity.py          anime (API diretta, vixcloud)
  anilist.py             copertine vere degli anime (banner/locandine via AniList)
  vixsrc.py              seconda sorgente per film/serie (stesso backend vixcloud)
  vixcloud.py            estrae l'm3u8 dall'embed (condiviso)
  risolutore_siti.py     domini aggiornati + cache su disco
  storage.py             recenti / preferiti / posizioni / preferenze di riproduzione
  downloader.py          download come HLS locale (segmenti paralleli, decifra AES)
  download_manager.py    download in background (stato, annulla) + libreria scaricati
  bridge.py              server-ponte locale (porta 8765): minuto, preferenze, comandi del player, video offline
  aggiornamenti.py       aggiornamento automatico (scarica solo i file cambiati, verifica, backup)
  versione.py            la versione installata (una riga; la sostituisce l'aggiornamento)
  _python_portatile.ps1  scarica il Python dedicato su Windows, se serve
  casting.py             trasmissione su Chromecast/Google TV (pychromecast, lato Python)
  browser.py             apre Chrome in modalità app (Win/Mac/Linux)
  home_component/        componente della home Netflix (caroselli cliccabili)
  requirements.txt       dipendenze (streamlit, requests, pycryptodome, imageio-ffmpeg, pychromecast)
  venv/ Download/ dati.json ...  ambiente e dati (creati al primo avvio)
```
