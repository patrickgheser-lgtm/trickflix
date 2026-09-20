import os
import re
import sys
import json
import socket

# Percorsi robusti (avvio da .bat / cartella diversa)
_BASE = os.path.dirname(os.path.abspath(__file__))
if _BASE not in sys.path:
    sys.path.insert(0, _BASE)
os.chdir(_BASE)

import streamlit as st
import streamlit.components.v1 as components

import streamingcommunity as sc
import animeunity as au
import vixsrc
import anilist
import casting
import downloader as dl
import download_manager as dm
import bridge
import aggiornamenti
from storage import (carica_dati, aggiungi_recente,
                     posizione, leggi_posizioni, leggi_pick, preferenze, leggi_vai, leggi_azione)

DOWNLOAD_DIR = dm.DOWNLOAD_DIR


def _safe_name(s):
    out = "".join((" " if c in '\\/:*?"<>|' else c) for c in (s or ""))
    return (out.strip() or "video")[:120]

st.set_page_config(page_title="TrickFlix", page_icon="🍿", layout="wide")
st.markdown("""
<style>
.block-container { padding-top: 3rem !important; }
.stButton>button { width: 100%; border-radius: 6px; }
</style>
""", unsafe_allow_html=True)

# ── Stato ──────────────────────────────────────────────────────────────
_def = {"vista": "home", "sel": None, "risultati": [], "m3u8": None, "titolo_player": "",
        "resume_key": "", "play_src": None, "n_mostrati": 12, "q_corrente": "", "tipo_corrente": "",
        "is_offline": False, "offline_is_file": False, "ultimo_pick_t": None,
        "ultimo_vai_t": (leggi_vai() or {}).get("t"), "vai_pendente": None,
        "ultima_azione_t": (leggi_azione() or {}).get("t"), "azione_pendente": None,
        "tab_home": "🏠 Home", "dettaglio_da": "🏠 Home", "player_torna": "dettaglio"}
for k, v in _def.items():
    st.session_state.setdefault(k, v)


@st.cache_data(ttl=3600)
def au_base():
    # resolver robusto in animeunity.py: Startpage + guida, validato col backend reale e
    # normalizzato per i redirect (www). Ritorna la base completa 'https://host' o None.
    return au.dominio()


def vai(vista):
    st.session_state.vista = vista


# ── Player Netflix custom su hls.js ──────────────────────────────────────
# Skin "Netflix-like" costruita a mano sopra hls.js: carica l'm3u8 vixcloud
# DIRETTO (CORS aperto, niente proxy) e usa le API hls.js per i menu:
#   audio   -> hls.audioTracks / hls.audioTrack   (dub IT vs originale)
#   qualità -> hls.levels / hls.currentLevel       (480/720/1080 + Auto)
#   sottot. -> hls.subtitleTracks / hls.subtitleTrack
# Auto-seleziona l'audio italiano. Scorciatoie tastiera, fullscreen, PiP,
# barra controlli, big play centrale, gradiente e titolo in alto.
_PLAYER_HTML = """
<!DOCTYPE html><html lang="it"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<script src="https://cdn.jsdelivr.net/npm/hls.js@1"></script>
<style>
 *{margin:0;padding:0;box-sizing:border-box}
 html,body{height:100%;overflow:hidden;background:#000}
 .tf{position:relative;width:100%;height:100vh;background:#000;display:flex;align-items:center;justify-content:center;
   font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,'Helvetica Neue',Arial,sans-serif;color:#fff;
   -webkit-font-smoothing:antialiased;user-select:none;overflow:hidden}
 .tf video{width:100%;height:100%;max-width:100%;max-height:100%;object-fit:contain;background:#000;display:block}

 /* overlay controlli con fade (i click passano al video; solo i figli interattivi li ricevono) */
 .tf-overlay{position:absolute;inset:0;z-index:10;transition:opacity .3s ease;pointer-events:none}
 .tf.hide-ui .tf-overlay{opacity:0}
 .tf.hide-ui{cursor:none}

 /* barra superiore + titolo */
 .tf-top{position:absolute;top:0;left:0;right:0;padding:1.4rem 2rem 5rem;
   background:linear-gradient(to bottom,#000,rgba(0,0,0,.55),transparent)}
 .tf-title{font-size:1.15rem;font-weight:600;color:#fff;text-shadow:0 1px 3px rgba(0,0,0,.5);
   white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:75%}

 /* spinner buffering */
 .tf-spin{position:absolute;inset:0;display:none;align-items:center;justify-content:center;z-index:12}
 .tf.buffering .tf-spin{display:flex}
 .tf-ring{width:56px;height:56px;border:4px solid rgba(255,255,255,.25);border-top-color:#e50914;border-radius:50%;animation:tf-spin 1s linear infinite}
 @keyframes tf-spin{to{transform:rotate(360deg)}}

 /* big play centrale (solo in pausa, niente buffering) */
 .tf-bigplay{position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);z-index:11;
   width:84px;height:84px;border-radius:50%;background:rgba(0,0,0,.45);-webkit-backdrop-filter:blur(4px);backdrop-filter:blur(4px);
   display:flex;align-items:center;justify-content:center;cursor:pointer;border:none;color:#fff;
   opacity:0;pointer-events:none;transition:opacity .25s ease,transform .15s ease}
 .tf.is-paused:not(.buffering) .tf-bigplay{opacity:1;pointer-events:auto}
 .tf-bigplay:hover{transform:translate(-50%,-50%) scale(1.06);background:rgba(0,0,0,.6)}
 .tf-bigplay svg{width:40px;height:40px;margin-left:4px}

 /* barra controlli */
 .tf-ctrl{position:absolute;bottom:0;left:0;right:0;z-index:11;pointer-events:auto;
   background:linear-gradient(to top,rgba(0,0,0,1) 0%,rgba(0,0,0,.6) 60%,transparent 100%);
   padding:5rem 2rem 1.25rem}

 /* progress bar */
 .tf-prog{position:relative;width:100%;height:.25rem;background:rgba(75,85,99,.4);border-radius:9999px;cursor:pointer;transition:height .15s ease;margin-bottom:.9rem}
 .tf-prog:hover{height:.4rem}
 .tf-prog-inner{position:absolute;inset:0;border-radius:9999px;overflow:hidden}
 .tf-buf{position:absolute;left:0;top:0;height:100%;width:0;background:rgba(156,163,175,.3)}
 .tf-watched{position:absolute;left:0;top:0;height:100%;width:0;background:#e50914}
 .tf-scrub{position:absolute;top:50%;left:0;width:.85rem;height:.85rem;background:#e50914;border-radius:50%;transform:translate(-50%,-50%) scale(0);transition:transform .12s ease;box-shadow:0 2px 6px rgba(0,0,0,.5)}
 .tf-prog:hover .tf-scrub{transform:translate(-50%,-50%) scale(1)}

 /* righe / gruppi / bottoni */
 .tf-row{display:flex;align-items:center;justify-content:space-between;position:relative}
 .tf-grp{display:flex;align-items:center;gap:.4rem}
 .tf-btn{padding:.5rem;border:none;background:transparent;color:#fff;cursor:pointer;border-radius:50%;
   display:flex;align-items:center;justify-content:center;transition:background-color .2s ease}
 .tf-btn:hover{background-color:rgba(255,255,255,.14)}
 .tf-btn svg{width:24px;height:24px;display:block}
 .tf-btn.tf-pp svg{width:28px;height:28px}
 .tf-time{margin-left:.45rem;font-size:.875rem;font-variant-numeric:tabular-nums}
 .tf-time .cur{color:#fff;font-weight:500}
 .tf-time .sep{color:#9ca3af;margin:0 .3rem}
 .tf-time .dur{color:#9ca3af}

 /* volume: slider verticale a comparsa */
 .tf-vol{position:relative;display:flex;align-items:center}
 .tf-volpop{position:absolute;bottom:100%;left:50%;transform:translateX(-50%);width:46px;height:148px;padding:14px 8px;
   background:rgba(0,0,0,.92);-webkit-backdrop-filter:blur(12px);backdrop-filter:blur(12px);border-radius:8px;margin-bottom:6px;
   display:flex;align-items:center;justify-content:center;opacity:0;pointer-events:none;transition:opacity .2s ease;
   box-shadow:0 12px 24px rgba(0,0,0,.5)}
 .tf-vol:hover .tf-volpop,.tf-volpop:hover{opacity:1;pointer-events:auto}
 .tf-volslider{-webkit-appearance:none;appearance:none;width:120px;height:6px;border-radius:3px;transform:rotate(-90deg);
   background:rgba(75,85,99,.55);cursor:pointer;outline:none}
 .tf-volslider::-webkit-slider-runnable-track{height:6px;border-radius:3px}
 .tf-volslider::-webkit-slider-thumb{-webkit-appearance:none;appearance:none;width:14px;height:14px;border-radius:50%;background:#e50914;margin-top:-4px;box-shadow:0 2px 6px rgba(0,0,0,.5);cursor:pointer}

 /* messaggino di conferma: il player non puo' ricevere risposte dal backend,
    quindi il riscontro immediato lo diamo qui */
 .tf-toast{position:absolute;left:50%;bottom:6.2rem;transform:translateX(-50%);z-index:25;max-width:80%;
   background:rgba(0,0,0,.88);-webkit-backdrop-filter:blur(10px);backdrop-filter:blur(10px);
   border:1px solid rgba(255,255,255,.16);border-radius:.5rem;padding:.6rem 1rem;font-size:.88rem;
   text-align:center;opacity:0;pointer-events:none;transition:opacity .25s ease}
 .tf-toast.show{opacity:1}

 /* popup episodi (stile Netflix): pannello sopra il video, si sfoglia MENTRE si guarda */
 .tf-eps{position:absolute;inset:0;z-index:20;display:none;background:rgba(0,0,0,.5);
   -webkit-backdrop-filter:blur(4px);backdrop-filter:blur(4px)}
 .tf-eps.open{display:flex;justify-content:flex-end}
 .tf-eps-pan{width:min(540px,100%);background:rgba(18,18,18,.97);border-left:1px solid rgba(255,255,255,.12);
   display:flex;flex-direction:column;box-shadow:-22px 0 50px rgba(0,0,0,.6)}
 .tf-eps-h{display:flex;align-items:center;gap:.5rem;padding:.75rem .8rem;flex:0 0 auto;
   border-bottom:1px solid rgba(255,255,255,.1)}
 .tf-eps-t{font-size:1rem;font-weight:600;flex:1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
 .tf-eps-l{flex:1 1 auto;overflow-y:auto;padding:.25rem 0}
 .tf-ep{display:flex;gap:.7rem;padding:.55rem .9rem;cursor:pointer;align-items:flex-start;border:none;
   background:transparent;color:#fff;width:100%;text-align:left;font:inherit}
 .tf-ep:hover{background:rgba(255,255,255,.09)}
 .tf-ep.cur{background:rgba(255,255,255,.14)}
 .tf-ep-n{width:1.5rem;text-align:right;color:#9ca3af;flex:0 0 auto;padding-top:.15rem;font-size:.95rem}
 .tf-ep-img{width:100px;height:57px;object-fit:cover;border-radius:.3rem;background:#262626;flex:0 0 auto}
 .tf-ep-txt{flex:1;min-width:0}
 .tf-ep-tt{font-size:.88rem;font-weight:500;display:flex;gap:.5rem;justify-content:space-between}
 .tf-ep-du{color:#9ca3af;font-weight:400;flex:0 0 auto}
 .tf-ep-pl{font-size:.76rem;color:#9ca3af;margin-top:.15rem;overflow:hidden;
   display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical}
 .tf-st{padding:.7rem 1rem;cursor:pointer;font-size:.95rem;display:flex;justify-content:space-between;
   border:none;background:transparent;color:#fff;width:100%;text-align:left;font:inherit}
 .tf-st:hover{background:rgba(255,255,255,.09)}
 .tf-st.cur{font-weight:600}
 .tf-st .tf-st-ora{color:#9ca3af;font-size:.8rem}

 /* menu impostazioni (audio/sottotitoli/qualità/velocità) */
 .tf-menu{position:absolute;right:2rem;bottom:5.4rem;z-index:13;min-width:250px;max-height:58vh;overflow-y:auto;
   background:rgba(0,0,0,.92);-webkit-backdrop-filter:blur(14px);backdrop-filter:blur(14px);border:1px solid rgba(255,255,255,.1);
   border-radius:.6rem;padding:.4rem 0;box-shadow:0 20px 45px rgba(0,0,0,.65);
   opacity:0;pointer-events:none;transform:translateY(8px);transition:opacity .18s ease,transform .18s ease}
 .tf-menu.open{opacity:1;pointer-events:auto;transform:none}
 .tf-sec+.tf-sec{border-top:1px solid rgba(255,255,255,.08);margin-top:.25rem;padding-top:.25rem}
 .tf-sec-h{font-size:.7rem;font-weight:700;letter-spacing:.07em;text-transform:uppercase;color:#9ca3af;padding:.55rem 1.1rem .25rem}
 .tf-opt{display:flex;align-items:center;gap:.65rem;padding:.55rem 1.1rem;font-size:.9rem;color:#d1d5db;cursor:pointer;transition:background .12s ease,color .12s ease}
 .tf-opt:hover{background:rgba(255,255,255,.08);color:#fff}
 .tf-opt.active{color:#fff;font-weight:600}
 .tf-dot{width:.45rem;height:.45rem;border-radius:50%;background:#e50914;flex:0 0 .45rem;visibility:hidden}
 .tf-opt.active .tf-dot{visibility:visible}

 /* sottotitoli nativi */
 .tf video::cue{background:transparent;color:#fff;font-weight:500;text-shadow:0 0 3px #000,0 2px 5px #000}
 .tf ::-webkit-scrollbar{width:8px}
 .tf ::-webkit-scrollbar-thumb{background:rgba(255,255,255,.3);border-radius:4px}
</style></head>
<body>
<div id="tf" class="tf is-paused buffering">
  <video id="v" playsinline crossorigin="anonymous"></video>

  <div class="tf-overlay" id="overlay">
    <div class="tf-top"><div class="tf-title">__TITLE__</div></div>

    <div class="tf-spin"><div class="tf-ring"></div></div>

    <button class="tf-bigplay" id="bigplay" title="Riproduci"></button>

    <div class="tf-ctrl" id="ctrl">
      <div class="tf-prog" id="prog">
        <div class="tf-prog-inner">
          <div class="tf-buf" id="buf"></div>
          <div class="tf-watched" id="watched"></div>
        </div>
        <div class="tf-scrub" id="scrub"></div>
      </div>
      <div class="tf-row">
        <div class="tf-grp">
          <button class="tf-btn tf-pp" id="b-play" title="Play/Pausa (k)"></button>
          <button class="tf-btn" id="b-back" title="Indietro 10s (j)"></button>
          <button class="tf-btn" id="b-fwd" title="Avanti 10s (l)"></button>
          <div class="tf-vol" id="volwrap">
            <button class="tf-btn" id="b-mute" title="Muto (m)"></button>
            <div class="tf-volpop"><input type="range" class="tf-volslider" id="volslider" min="0" max="1" step="0.01" value="1"></div>
          </div>
          <span class="tf-time"><span class="cur" id="t-cur">0:00</span><span class="sep">/</span><span class="dur" id="t-dur">0:00</span></span>
        </div>
        <div class="tf-grp">
          <button class="tf-btn" id="b-next" title="Prossimo episodio" style="display:none"></button>
          <button class="tf-btn" id="b-eps" title="Episodi" style="display:none"></button>
          <button class="tf-btn" id="b-dl" title="Scarica" style="display:none"></button>
          <button class="tf-btn" id="b-cast" title="Trasmetti su TV" style="display:none"></button>
          <button class="tf-btn" id="b-cc" title="Audio e sottotitoli"></button>
          <button class="tf-btn" id="b-gear" title="Qualità e velocità"></button>
          <button class="tf-btn" id="b-pip" title="Picture in Picture"></button>
          <button class="tf-btn" id="b-fs" title="Schermo intero (f)"></button>
        </div>
      </div>
    </div>

    <div class="tf-menu" id="menu-av">
      <div class="tf-sec"><div class="tf-sec-h">Audio</div><div id="m-audio"></div></div>
      <div class="tf-sec"><div class="tf-sec-h">Sottotitoli</div><div id="m-subs"></div></div>
    </div>
    <div class="tf-menu" id="menu-cast">
      <div class="tf-sec"><div class="tf-sec-h">Trasmetti su</div><div id="m-cast"></div></div>
    </div>
    <div class="tf-menu" id="menu-qs">
      <div class="tf-sec"><div class="tf-sec-h">Qualità</div><div id="m-quality"></div></div>
      <div class="tf-sec"><div class="tf-sec-h">Velocità</div><div id="m-speed"></div></div>
    </div>
  </div>

  <div class="tf-toast" id="toast"></div>

  <!-- popup episodi: FUORI da #overlay, altrimenti sparisce quando i controlli
       si auto-nascondono (classe hide-ui) mentre lo stai sfogliando -->
  <div class="tf-eps" id="eps">
    <div class="tf-eps-pan">
      <div class="tf-eps-h">
        <button class="tf-btn" id="b-eps-back" title="Scegli la stagione" style="display:none"></button>
        <span class="tf-eps-t" id="eps-titolo">Episodi</span>
        <button class="tf-btn" id="b-eps-close" title="Chiudi"></button>
      </div>
      <div class="tf-eps-l" id="eps-lista"></div>
    </div>
  </div>
</div>

<script>
(function(){
  var SRC = "__SRC__";
  var RKEY = "__RESUMEKEY__";   // chiave per salvare/riprendere il minuto (continua a guardare)
  var ISFILE = ("__ISFILE__" === "1");   // 1 = file locale offline (mp4), non HLS
  // Preferenze di riproduzione (lingua audio, sottotitoli, qualita'): valgono come
  // default per QUESTA serie. Le manda Python gia' pronte; quando l'utente cambia
  // qualcosa si rimandano al ponte (stesso trucco del minuto: l'iframe ha origine
  // opaca e non puo' usare localStorage).
  // Episodi della serie, iniettati da Python: l'iframe non puo' chiederli a runtime
  // (origine opaca -> Chrome blocca fetch e script verso localhost), quindi arrivano gia' pronti.
  var EPS = __EPISODI__;        // [{n:"1", eps:[{id,num,nome,img,dur,plot}]}]
  var EPCUR = "__EPCORR__";     // id dell'episodio in riproduzione
  var DLSTATO = "__DLSTATO__";   // "no" | "coda" | "fatto": stato del download di QUESTO video
  var CASTDEV = __CASTDEV__;     // dispositivi trovati in rete (cercati in background da Python)
  var CASTSCAN = ("__CASTSCAN__" === "1");   // ricerca ancora in corso
  var CASTABILE = ("__CASTABILE__" === "1"); // castabile solo lo streaming ONLINE
  var PKEY = "__PREFKEY__";
  var PREF = {audio:"__PREFAUDIO__", sub:"__PREFSUB__", subname:"__PREFSUBNAME__", qual:"__PREFQUAL__"};
  // Icone autentiche del player Netflix (estratte dall'estensione) + PiP Material.
  var IC = {
    play:['M5 2.7a1 1 0 0 1 1.48-.88l16.93 9.3a1 1 0 0 1 0 1.76l-16.93 9.3A1 1 0 0 1 5 21.31z','0 0 24 24'],
    pause:['M4.5 3a.5.5 0 0 0-.5.5v17c0 .28.22.5.5.5h5a.5.5 0 0 0 .5-.5v-17a.5.5 0 0 0-.5-.5zm10 0a.5.5 0 0 0-.5.5v17c0 .28.22.5.5.5h5a.5.5 0 0 0 .5-.5v-17a.5.5 0 0 0-.5-.5z','0 0 24 24'],
    back10:['M11.02 2.05A10 10 0 1 1 2 12H0a12 12 0 1 0 5-9.75V1H3v4a1 1 0 0 0 1 1h4V4H6a10 10 0 0 1 5.02-1.95M2 4v3h3v2H1a1 1 0 0 1-1-1V4zm12.13 12q-.88 0-1.53-.42-.64-.44-1-1.22a5 5 0 0 1-.35-1.86q0-1.05.35-1.85.36-.79 1-1.22A2.7 2.7 0 0 1 14.13 9a2.65 2.65 0 0 1 2.52 1.65q.35.79.35 1.85 0 1.07-.35 1.86a3 3 0 0 1-1.01 1.22 2.7 2.7 0 0 1-1.52.42m0-1.35q.59 0 .91-.56.34-.56.34-1.59 0-1.01-.34-1.58-.33-.57-.91-.57-.6 0-.92.57-.34.56-.34 1.58t.34 1.6q.33.54.91.55m-5.53 1.2v-5.13l-1.6.42V9.82l3.2-.8v6.84z','0 0 24 24'],
    fwd10:['M6.44 3.69A10 10 0 0 1 18 4h-2v2h4a1 1 0 0 0 1-1V1h-2v1.25A12 12 0 1 0 24 12h-2A10 10 0 1 1 6.44 3.69M22 4v3h-3v2h4a1 1 0 0 0 1-1V4zm-9.4 11.58q.66.42 1.53.42a2.7 2.7 0 0 0 1.5-.42q.67-.44 1.02-1.22.35-.8.35-1.86 0-1.05-.35-1.85A2.65 2.65 0 0 0 14.13 9a2.7 2.7 0 0 0-1.53.43q-.64.44-1 1.22a4.5 4.5 0 0 0-.35 1.85q0 1.07.35 1.86.36.78 1 1.22m2.44-1.49q-.33.56-.91.56-.6 0-.92-.56-.34-.56-.34-1.59 0-1.01.34-1.58.33-.57.91-.57.6 0 .92.57.34.56.34 1.58t-.34 1.6M8.6 10.72v5.14h1.6V9.02l-3.2.8v1.32z','0 0 24 24'],
    volHigh:['M24 12a14 14 0 0 0-4.1-9.9l-1.41 1.41a12 12 0 0 1 0 16.98l1.41 1.41A14 14 0 0 0 24 12M11 4a1 1 0 0 0-1.7-.7L4.58 8H1a1 1 0 0 0-1 1v6a1 1 0 0 0 1 1h3.59l4.7 4.7A1 1 0 0 0 11 20zM5.7 9.7 9 6.42V17.6l-3.3-3.3-.29-.29H2v-4h3.41zM16 12a6 6 0 0 0-1.76-4.24l-1.41 1.41a4 4 0 0 1 0 5.66l1.41 1.41A6 6 0 0 0 16 12m1.07-7.07a10 10 0 0 1 0 14.14l-1.41-1.41a8 8 0 0 0 0-11.32z','0 0 24 24'],
    volMed:['M11 4a1 1 0 0 0-1.7-.7L4.58 8H1a1 1 0 0 0-1 1v6a1 1 0 0 0 1 1h3.59l4.7 4.7A1 1 0 0 0 11 20zM5.7 9.7 9 6.42V17.6l-3.3-3.3-.29-.29H2v-4h3.41zm11.37-4.77a10 10 0 0 1 0 14.14l-1.41-1.41a8 8 0 0 0 0-11.32zm-2.83 2.83a6 6 0 0 1 0 8.48l-1.41-1.41a4 4 0 0 0 0-5.66z','0 0 24 24'],
    volLow:['M11 4a1 1 0 0 0-1.7-.7L4.58 8H1a1 1 0 0 0-1 1v6a1 1 0 0 0 1 1h3.59l4.7 4.7A1 1 0 0 0 11 20zM5.7 9.7 9 6.42V17.6l-3.3-3.3-.29-.29H2v-4h3.41zM16 12a6 6 0 0 0-1.76-4.24l-1.41 1.41a4 4 0 0 1 0 5.66l1.41 1.41A6 6 0 0 0 16 12','0 0 24 24'],
    volOff:['M11 4a1 1 0 0 0-1.7-.7L4.58 8H1a1 1 0 0 0-1 1v6a1 1 0 0 0 1 1h3.59l4.7 4.7A1 1 0 0 0 11 20zM5.7 9.7 9 6.42V17.6l-3.3-3.3-.29-.29H2v-4h3.41zm9.6 0 2.29 2.3-2.3 2.3 1.42 1.4L19 13.42l2.3 2.3 1.4-1.42-2.28-2.3 2.3-2.3-1.42-1.4-2.3 2.28-2.3-2.3z','0 0 24 24'],
    subs:['M1 3a1 1 0 0 1 1-1h20a1 1 0 0 1 1 1v14a1 1 0 0 1-1 1h-3v3a1 1 0 0 1-1.55.83L11.7 18H2a1 1 0 0 1-1-1zm2 1v12h9.3l.25.17L17 19.13V16h4V4zm7 5H5V7h5zm9 2h-5v2h5zm-7 2H5v-2h7zm7-6h-7v2h7z','0 0 24 24'],
    // icone fornite dall'utente (PNG bianchi su trasparente, vettorizzati con potrace)
    episodi:['M1.64,20.89C0.88,20.68 0.3,20.1 0.07,19.32C-0.03,18.95 -0.04,13.1 0.07,12.69C0.28,11.89 0.87,11.3 1.67,11.09C1.91,11.02 2.71,11.02 8.03,11.02C13.51,11.02 14.14,11.02 14.38,11.09C14.76,11.2 14.95,11.31 15.25,11.58C15.56,11.86 15.76,12.16 15.89,12.55C15.98,12.83 15.98,12.93 15.98,15.97C15.98,19.41 15.99,19.35 15.7,19.85C15.54,20.14 15.09,20.58 14.82,20.71C14.34,20.96 14.57,20.95 7.97,20.95C3.17,20.95 1.8,20.93 1.64,20.89ZM13.9,18.87L14.02,18.75L14.02,15.98L14.02,13.21L13.9,13.1L13.79,12.98L8.0,12.98C2.37,12.98 2.21,12.99 2.1,13.07L1.99,13.16L1.99,15.98L1.99,18.81L2.1,18.89C2.21,18.98 2.37,18.98 8.0,18.98L13.79,18.98L13.9,18.87ZM18.63,16.93C18.53,16.88 18.38,16.78 18.31,16.71C18.01,16.41 18.03,16.58 18.0,12.72L17.98,9.19L17.87,9.08L17.76,8.98L11.21,8.95L4.66,8.93L4.49,8.82C4.12,8.59 3.94,8.08 4.1,7.67C4.19,7.41 4.48,7.15 4.72,7.08C4.84,7.05 6.99,7.03 11.49,7.03C18.68,7.03 18.34,7.02 18.85,7.3C19.14,7.46 19.54,7.86 19.7,8.15C19.97,8.64 19.97,8.6 19.97,12.6C19.97,16.7 19.99,16.44 19.64,16.75C19.35,17.02 18.97,17.08 18.63,16.93ZM22.62,12.94C22.51,12.89 22.37,12.79 22.3,12.72C22.02,12.42 22.03,12.56 22.03,8.79C22.03,5.11 22.03,5.14 21.81,5.04C21.76,5.02 18.82,4.99 15.26,4.99C8.13,4.97 8.62,5.0 8.31,4.68C7.83,4.18 7.96,3.46 8.59,3.14C8.76,3.05 8.96,3.05 15.46,3.05C21.91,3.05 22.17,3.05 22.45,3.14C22.81,3.25 23.13,3.46 23.41,3.75C23.67,4.03 23.79,4.27 23.91,4.72C24.0,5.06 24.0,5.27 24.0,8.62C24.0,10.95 23.98,12.22 23.95,12.34C23.8,12.88 23.13,13.18 22.62,12.94Z','0 0 24 24'],
    nextEp:['M22.48,22.76C22.26,22.71 22.16,22.64 21.96,22.43C21.6,22.02 21.63,23.04 21.63,12.0C21.63,2.63 21.64,2.1 21.72,1.93C22.03,1.27 22.81,1.0 23.42,1.36C23.65,1.49 23.87,1.8 23.95,2.08C23.98,2.19 24.0,5.76 24.0,12.05C24.0,21.79 24.0,21.84 23.9,22.05C23.8,22.29 23.53,22.59 23.33,22.69C23.18,22.77 22.68,22.82 22.48,22.76ZM1.19,22.16C0.57,21.94 0.16,21.44 0.05,20.78C-0.02,20.37 -0.02,3.52 0.05,3.14C0.11,2.78 0.17,2.62 0.35,2.38C0.65,1.95 1.21,1.66 1.76,1.66C2.21,1.66 2.44,1.76 3.45,2.38C3.68,2.52 4.27,2.88 4.76,3.17C5.25,3.47 5.99,3.92 6.4,4.17C6.81,4.43 7.31,4.73 7.5,4.84C7.69,4.96 8.08,5.19 8.37,5.37C8.65,5.54 9.33,5.95 9.87,6.28C10.41,6.61 11.13,7.05 11.46,7.26C12.01,7.59 13.54,8.53 15.33,9.61C16.75,10.47 16.94,10.62 17.16,11.1C17.36,11.54 17.42,11.87 17.35,12.25C17.21,12.98 16.85,13.41 15.96,13.95C15.52,14.21 13.1,15.69 10.84,17.06C10.5,17.27 9.38,17.95 8.36,18.57C6.27,19.84 5.86,20.09 4.2,21.12C3.55,21.51 2.86,21.92 2.66,22.03C2.32,22.2 2.25,22.22 1.86,22.23C1.53,22.24 1.37,22.22 1.19,22.16ZM3.74,18.6C4.53,18.12 6.3,17.03 7.24,16.45C7.53,16.28 8.04,15.96 8.39,15.75C8.74,15.54 9.32,15.18 9.68,14.96C10.04,14.74 10.63,14.38 10.99,14.17C12.31,13.37 13.67,12.53 13.75,12.45C13.96,12.27 14.02,11.92 13.88,11.66C13.78,11.47 13.71,11.42 12.91,10.94C12.55,10.72 11.95,10.35 11.58,10.12C10.99,9.76 10.53,9.48 9.5,8.86C9.37,8.78 8.95,8.52 8.57,8.28C8.18,8.04 7.46,7.6 6.97,7.3C6.47,7.0 5.79,6.58 5.44,6.37C3.25,5.03 3.28,5.05 3.11,5.02C2.91,4.98 2.65,5.1 2.51,5.29C2.41,5.42 2.41,5.44 2.4,11.88C2.39,16.27 2.41,18.38 2.44,18.48C2.5,18.64 2.7,18.85 2.84,18.88C3.06,18.94 3.29,18.87 3.74,18.6Z','0 0 24 24'],
    indietro:['M15.7 4.3a1 1 0 0 1 0 1.4L9.42 12l6.3 6.3a1 1 0 0 1-1.42 1.4l-7-7a1 1 0 0 1 0-1.4l7-7a1 1 0 0 1 1.4 0z','0 0 24 24'],
    scarica:['M0.52,23.86C0.3,23.76 0.2,23.66 0.08,23.44C-0.1,23.08 0.06,22.59 0.43,22.39C0.6,22.29 0.64,22.29 6.11,22.29C9.73,22.29 11.63,22.27 11.65,22.24C11.66,22.22 11.66,22.2 11.63,22.2C11.57,22.2 7.76,18.23 4.73,15.02C3.88,14.12 3.78,13.97 3.83,13.65C3.9,13.19 4.28,12.91 4.75,12.98C4.93,13.01 5.01,13.08 5.56,13.63C6.23,14.3 7.81,15.96 9.84,18.11C10.55,18.86 11.15,19.47 11.17,19.47C11.19,19.47 11.2,15.27 11.2,10.13C11.2,3.28 11.22,0.74 11.26,0.63C11.32,0.44 11.5,0.23 11.69,0.13C12.0,-0.03 12.5,0.15 12.69,0.51C12.77,0.65 12.77,1.22 12.8,10.09L12.82,19.51L14.34,17.92C19.28,12.74 19.05,12.96 19.41,12.96C19.97,12.96 20.36,13.62 20.09,14.12C20.02,14.26 19.59,14.72 17.13,17.28C16.31,18.14 15.28,19.23 14.84,19.69C14.4,20.15 13.67,20.92 13.22,21.38C12.65,21.97 12.41,22.25 12.46,22.26C12.49,22.28 14.97,22.29 17.96,22.29L23.41,22.29L23.6,22.41C23.96,22.61 24.1,23.09 23.91,23.45C23.8,23.67 23.7,23.76 23.47,23.86C23.32,23.92 22.06,23.93 11.99,23.93C2.03,23.93 0.66,23.92 0.52,23.86Z','0 0 24 24'],
    cast:['M0.03,22.02C0.01,22.01 -0.0,21.48 -0.0,20.85L0.0,19.71L0.11,19.71C0.82,19.71 1.72,20.29 2.06,20.97C2.22,21.28 2.37,21.87 2.33,21.98C2.3,22.04 2.13,22.05 1.18,22.05C0.57,22.05 0.05,22.04 0.03,22.02ZM4.09,22.0C4.07,21.96 4.03,21.79 4.02,21.6C3.99,21.23 3.78,20.55 3.58,20.2C2.9,18.96 1.66,18.11 0.34,17.99L0.0,17.96L0.0,17.15L0.0,16.34L0.29,16.36C1.14,16.44 1.77,16.61 2.47,16.96C4.14,17.8 5.29,19.36 5.6,21.23C5.64,21.47 5.67,21.75 5.66,21.85L5.65,22.03L4.89,22.04C4.33,22.05 4.13,22.04 4.09,22.0ZM7.42,22.0C7.38,21.97 7.36,21.81 7.36,21.64C7.36,21.07 7.15,20.11 6.89,19.44C6.47,18.39 5.9,17.54 5.05,16.73C3.98,15.7 2.58,14.99 1.13,14.75C0.81,14.69 0.43,14.65 0.28,14.65L0.0,14.65L0.0,13.82L0.0,13.0L0.5,13.03C4.03,13.26 7.26,15.7 8.45,19.03C8.76,19.92 8.9,20.52 9.0,21.52C9.02,21.8 9.02,21.96 8.99,22.0C8.92,22.08 7.5,22.08 7.42,22.0ZM10.76,22.01C10.74,21.99 10.71,21.7 10.69,21.38C10.66,21.06 10.63,20.74 10.62,20.68C10.61,20.63 10.59,20.5 10.57,20.41C10.33,18.68 9.41,16.68 8.19,15.21C6.61,13.34 4.31,11.96 1.92,11.49C1.44,11.39 0.51,11.27 0.23,11.27L-0.0,11.27L0.01,10.46L0.02,9.66L0.38,9.67C1.08,9.69 2.06,9.84 2.81,10.03C5.86,10.8 8.52,12.69 10.29,15.35C10.96,16.36 11.66,17.93 11.95,19.09C12.21,20.11 12.43,21.89 12.31,22.0C12.25,22.07 10.8,22.07 10.76,22.01ZM14.04,21.46C14.03,21.13 14.0,20.73 13.98,20.57L13.96,20.27L17.91,20.27C21.5,20.27 21.88,20.27 21.98,20.2C22.23,20.02 22.22,20.42 22.22,12.0C22.22,3.53 22.23,4.03 21.97,3.85C21.88,3.78 20.87,3.77 12.0,3.77C2.95,3.77 2.12,3.78 2.02,3.85C1.79,4.01 1.78,4.1 1.78,6.09L1.78,7.95L0.89,7.95L0.0,7.95L0.0,5.89C0.0,3.97 0.01,3.81 0.09,3.53C0.32,2.78 0.88,2.24 1.63,2.03C1.93,1.95 2.4,1.95 11.99,1.95C22.89,1.95 22.29,1.93 22.8,2.19C23.29,2.43 23.71,2.92 23.89,3.45L24.0,3.78L24.0,12.02C24.0,18.93 23.99,20.28 23.93,20.47C23.7,21.24 23.14,21.79 22.38,21.98C22.14,22.04 21.55,22.05 18.09,22.05L14.08,22.05L14.04,21.46Z','0 0 24 24'],
    chiudi:['M4.3 4.3a1 1 0 0 1 1.4 0L12 10.6l6.3-6.3a1 1 0 1 1 1.4 1.4L13.4 12l6.3 6.3a1 1 0 0 1-1.4 1.4L12 13.4l-6.3 6.3a1 1 0 0 1-1.4-1.4L10.6 12 4.3 5.7a1 1 0 0 1 0-1.4z','0 0 24 24'],
    speed:['M19.06 6.27a9.7 9.7 0 0 0-14.12 0 10.8 10.8 0 0 0 0 14.82L3.5 22.47a12.8 12.8 0 0 1 0-17.59 11.7 11.7 0 0 1 17 0 12.8 12.8 0 0 1 0 17.59l-1.44-1.38a10.8 10.8 0 0 0 0-14.82M15 14a3 3 0 1 1-1.7-2.7l3-3 1.4 1.4-3 3q.3.6.3 1.3','0 0 24 24'],
    fsEnter:['M0 5c0-1.1.9-2 2-2h7v2H2v4H0zm22 0h-7V3h7a2 2 0 0 1 2 2v4h-2zM2 15v4h7v2H2a2 2 0 0 1-2-2v-4zm20 4v-4h2v4a2 2 0 0 1-2 2h-7v-2z','0 0 24 24'],
    fsExit:['M24 8h-5V3h-2v7h7zM0 16h5v5h2v-7H0zm7-6H0V8h5V3h2zm12 11v-5h5v-2h-7v7z','0 0 24 24'],
    pip:['M146.67-160q-27 0-46.84-19.83Q80-199.67 80-226.67v-506.66q0-27 19.83-46.84Q119.67-800 146.67-800h666.66q27 0 46.84 19.83Q880-760.33 880-733.33v506.66q0 27-19.83 46.84Q840.33-160 813.33-160H146.67Zm0-66.67h666.66v-506.66H146.67v506.66Zm0 0v-506.66 506.66ZM444-442h330v-251.33H444V-442Zm66.67-66.67v-118h196.66v118H510.67Z','0 -960 960 960']
  };
  function svg(key){ var ic=IC[key]; return '<svg viewBox="'+ic[1]+'" width="24" height="24" aria-hidden="true"><path fill="currentColor" fill-rule="evenodd" clip-rule="evenodd" d="'+ic[0]+'"/></svg>'; }
  function $(id){ return document.getElementById(id); }
  var tf=$('tf'), v=$('v'), menuAV=$('menu-av'), menuQS=$('menu-qs'), menuCast=$('menu-cast'), prog=$('prog'), vs=$('volslider');
  var hls=null, lastSub=-1, hideTimer=null;

  function fmt(t){
    if(!isFinite(t)||t<0){ t=0; }
    t=Math.floor(t);
    var h=Math.floor(t/3600), m=Math.floor((t%3600)/60), s=t%60;
    var mm=(h>0&&m<10)?('0'+m):(''+m);
    var ss=s<10?('0'+s):(''+s);
    return (h>0?(h+':'):'')+mm+':'+ss;
  }

  // ---- icone statiche ----
  $('b-back').innerHTML=svg('back10'); $('b-fwd').innerHTML=svg('fwd10');
  $('b-cc').innerHTML=svg('subs'); $('b-gear').innerHTML=svg('speed');
  $('b-eps').innerHTML=svg('episodi'); $('b-next').innerHTML=svg('nextEp');
  $('b-eps-back').innerHTML=svg('indietro'); $('b-eps-close').innerHTML=svg('chiudi');
  $('b-dl').innerHTML=svg('scarica'); $('b-cast').innerHTML=svg('cast');
  if(DLSTATO!=='mai'){ $('b-dl').style.display=''; }        // nascosto solo per i video offline
  if(CASTABILE){ $('b-cast').style.display=''; }
  if(EPS.length){ $('b-eps').style.display=''; }          // solo per serie/anime
  if(prossimoEp()){ $('b-next').style.display=''; }        // nascosto sull'ultimo episodio
  $('b-pip').innerHTML=svg('pip'); $('bigplay').innerHTML=svg('play');

  // ---- play / pausa ----
  function paintPlay(){ $('b-play').innerHTML=svg(v.paused?'play':'pause'); tf.classList.toggle('is-paused', v.paused); }
  function togglePlay(){ if(v.paused){ v.play().catch(function(){}); } else { v.pause(); } }
  v.addEventListener('play', function(){ paintPlay(); scheduleHide(); });
  v.addEventListener('pause', function(){ paintPlay(); showUI(); });
  v.addEventListener('waiting', function(){ tf.classList.add('buffering'); });
  v.addEventListener('playing', function(){ tf.classList.remove('buffering'); });
  v.addEventListener('canplay', function(){ tf.classList.remove('buffering'); });

  // ---- avanzamento ----
  function refresh(){
    var d=v.duration||0, c=v.currentTime||0, p=d?(c/d*100):0;
    $('watched').style.width=p+'%'; $('scrub').style.left=p+'%';
    $('t-cur').textContent=fmt(c);
    if(d){ $('t-dur').textContent=fmt(d); }
    try{ if(v.buffered.length){ var e=v.buffered.end(v.buffered.length-1); $('buf').style.width=(d?Math.min(100,e/d*100):0)+'%'; } }catch(err){}
  }
  v.addEventListener('timeupdate', refresh);
  v.addEventListener('durationchange', refresh);

  // ---- seek ----
  var dragging=false;
  function seekTo(x){ var r=prog.getBoundingClientRect(); var ratio=Math.max(0,Math.min(1,(x-r.left)/r.width)); if(v.duration){ v.currentTime=ratio*v.duration; } }
  prog.addEventListener('mousedown', function(e){ dragging=true; seekTo(e.clientX); e.preventDefault(); });
  window.addEventListener('mousemove', function(e){ if(dragging){ seekTo(e.clientX); } });
  window.addEventListener('mouseup', function(){ dragging=false; });

  // ---- volume ----
  function volKey(){ if(v.muted||v.volume===0){ return 'volOff'; } if(v.volume<0.34){ return 'volLow'; } if(v.volume<0.67){ return 'volMed'; } return 'volHigh'; }
  function paintVol(){
    var lv=v.muted?0:v.volume, p=lv*100;
    vs.value=lv;
    vs.style.background='linear-gradient(to right,#e50914 '+p+'%,rgba(75,85,99,.55) '+p+'%)';
    $('b-mute').innerHTML=svg(volKey());
  }
  function setVol(val){ val=Math.max(0,Math.min(1,val)); v.volume=val; v.muted=(val===0); }
  function toggleMute(){ v.muted=!v.muted; }
  vs.addEventListener('input', function(){ setVol(parseFloat(vs.value)); });
  v.addEventListener('volumechange', paintVol);

  // ---- fullscreen / PiP ----
  function paintFs(){ $('b-fs').innerHTML=svg(document.fullscreenElement?'fsExit':'fsEnter'); }
  function toggleFs(){
    if(document.fullscreenElement){ document.exitFullscreen(); }
    else { var fn=tf.requestFullscreen||tf.webkitRequestFullscreen; if(fn){ fn.call(tf); } }
  }
  document.addEventListener('fullscreenchange', paintFs);
  function togglePip(){ try{ if(document.pictureInPictureElement){ document.exitPictureInPicture(); } else if(v.requestPictureInPicture){ v.requestPictureInPicture(); } }catch(e){} }

  // ---- etichette tracce ----
  function audioLabel(tr){
    var L=(tr.lang||'').toLowerCase(), n=tr.name||'';
    if(L.indexOf('it')===0||/ital/i.test(n)){ return 'Italiano'; }
    if(L.indexOf('en')===0||/eng/i.test(n)){ return 'Inglese (originale)'; }
    if(L.indexOf('ja')===0||/jap|japan/i.test(n)){ return 'Giapponese (originale)'; }
    return n||L||'Traccia';
  }
  function subLabel(tr){ return (tr.name||tr.lang||'Sottotitoli'); }

  // Lingua normalizzata (ita/it -> it, jpn -> ja). Fra un episodio e l'altro le tracce
  // cambiano numero e ordine, quindi le preferenze si confrontano per LINGUA, mai per indice.
  function normLang(L){
    L=(L||'').toLowerCase();
    var m={ita:'it',eng:'en',jpn:'ja',jap:'ja',spa:'es',fra:'fr',fre:'fr',deu:'de',ger:'de',por:'pt',rus:'ru',chi:'zh',zho:'zh'};
    return m[L]||L.slice(0,2);
  }
  function trackLang(tr){
    var L=normLang(tr&&tr.lang||'');
    if(L){ return L; }
    var n=((tr&&tr.name)||'').toLowerCase();
    if(/ital/.test(n)){ return 'it'; }
    if(/ingl|engl/.test(n)){ return 'en'; }
    if(/giappo|japan/.test(n)){ return 'ja'; }
    return '';
  }
  // L'utente ha scelto qualcosa: diventa il default di questa serie (e l'ultimo usato in generale).
  // Si manda SOLO il campo cambiato: se salvassimo anche gli altri, una qualita' scelta
  // automaticamente da hls verrebbe "congelata" per sbaglio a ogni cambio di lingua.
  function savePrefs(campi){
    if(!PKEY||!campi){ return; }
    try{
      var u="http://localhost:8765/prefs?uid="+encodeURIComponent(PKEY);
      for(var k in campi){ if(Object.prototype.hasOwnProperty.call(campi,k)){ u+="&"+k+"="+encodeURIComponent(campi[k]); } }
      var img=new Image(); img.src=u+"&_="+Date.now();
    }catch(e){}
  }

  // Scelte dell'utente: aggiornano anche PREF, cosi' l'"insistenza" qui sotto
  // difende la NUOVA scelta e non quella vecchia.
  function scegliAudio(i){
    if(!hls||!hls.audioTracks[i]){ return; }
    hls.audioTrack=i;
    PREF.audio=trackLang(hls.audioTracks[i])||'';
    prefAudioFatto=true; tentAudio=0;
    buildAudio(); savePrefs({audio:PREF.audio});
  }
  function scegliSub(i){
    if(!hls){ return; }
    hls.subtitleTrack=i;
    if(i<0){ PREF.sub='off'; PREF.subname=''; }
    else if(hls.subtitleTracks[i]){ PREF.sub=trackLang(hls.subtitleTracks[i])||'on'; PREF.subname=hls.subtitleTracks[i].name||''; lastSub=i; }
    tentSub=0;
    buildSubs(); savePrefs({sub:PREF.sub, subname:PREF.subname});
  }
  function scegliQual(i){
    if(!hls){ return; }
    hls.currentLevel=i;
    PREF.qual=(i<0)?'auto':String((hls.levels[i]||{}).height||'auto');
    buildQuality(); savePrefs({qual:PREF.qual});
  }

  // ---- messaggino di conferma ----
  function toast(msg){
    var t=$('toast'); t.textContent=msg; t.classList.add('show');
    clearTimeout(t.__h); t.__h=setTimeout(function(){ t.classList.remove('show'); }, 3400);
  }
  // Richiesta generica al backend (download / cast): stesso beacon-immagine del resto,
  // l'unico canale che l'iframe a origine opaca puo' usare.
  function azione(nome, dato){
    try{
      var u="http://localhost:8765/azione?a="+encodeURIComponent(nome)+
            "&d="+encodeURIComponent(dato||"")+"&_="+Date.now();
      var img=new Image(); img.src=u;
    }catch(e){}
  }

  // ---- download: un click, massima qualita', tutte le tracce ----
  function scarica(){
    if(DLSTATO==='fatto'){ toast("Gia' scaricato: lo trovi in Home > Download."); return; }
    if(DLSTATO==='coda'){ toast("Download gia' in corso. Stato in Home > Download."); return; }
    azione('scarica');
    DLSTATO='coda';
    toast("Download avviato in massima qualita', con tutte le tracce audio e i sottotitoli.");
  }

  // ---- cast: elenco dei dispositivi trovati ----
  function buildCast(){
    var el=$('m-cast'); clear(el);
    if(CASTDEV.length){
      CASTDEV.forEach(function(nome){
        el.appendChild(mkOpt(nome, false, function(){
          azione('cast', nome); closeMenus(); toast('Trasmetto su «'+nome+'»…');
        }));
      });
      el.appendChild(mkOpt('Ferma trasmissione', false, function(){
        azione('cast-stop'); closeMenus(); toast('Trasmissione interrotta.');
      }));
    } else {
      el.appendChild(mkOpt(CASTSCAN?'Cerco dispositivi…':'Nessun dispositivo trovato', false, function(){}));
    }
    el.appendChild(mkOpt('Cerca di nuovo', false, function(){
      azione('cast-scan'); closeMenus(); toast('Cerco dispositivi nella rete…');
    }));
  }
  function toggleCast(){
    var open=menuCast.classList.contains('open'); closeMenus();
    if(!open){ buildCast(); placeMenu(menuCast,$('b-cast')); menuCast.classList.add('open'); }
    showUI();
  }

  // ---- popup episodi (stile Netflix) + prossimo episodio ----
  function posizioneCorrente(){
    for(var i=0;i<EPS.length;i++){
      for(var j=0;j<EPS[i].eps.length;j++){ if(EPS[i].eps[j].id===EPCUR){ return [i,j]; } }
    }
    return [0,-1];
  }
  // Il cambio episodio lo esegue Python: da qui parte solo la richiesta, con lo stesso
  // "beacon" immagine usato per il minuto (l'unico canale che l'iframe opaco puo' usare).
  function vaiEp(ep, stagione){
    try{
      var u="http://localhost:8765/vai?ep="+encodeURIComponent(ep.id)+
            "&s="+encodeURIComponent(stagione||"")+"&n="+encodeURIComponent(ep.num||"")+
            "&_="+Date.now();
      var img=new Image(); img.src=u;
    }catch(e){}
    chiudiEps();
  }
  function prossimoEp(){
    var p=posizioneCorrente(), i=p[0], j=p[1];
    if(j<0){ return null; }
    if(j+1<EPS[i].eps.length){ return {s:EPS[i].n, e:EPS[i].eps[j+1]}; }
    if(i+1<EPS.length && EPS[i+1].eps.length){ return {s:EPS[i+1].n, e:EPS[i+1].eps[0]}; }
    return null;                      // ultimo episodio disponibile
  }
  function mostraEpisodi(idx){
    var st=EPS[idx]; if(!st){ return; }
    var lista=$('eps-lista');
    $('eps-titolo').textContent = st.n ? ('Stagione '+st.n) : 'Episodi';
    $('b-eps-back').style.display = (EPS.length>1) ? '' : 'none';
    clear(lista);
    st.eps.forEach(function(e){
      var b=document.createElement('button');
      b.className='tf-ep'+(e.id===EPCUR?' cur':'');
      var n=document.createElement('span'); n.className='tf-ep-n'; n.textContent=e.num||'';
      b.appendChild(n);
      if(e.img){
        var im=document.createElement('img'); im.className='tf-ep-img';
        im.loading='lazy'; im.src=e.img; im.alt=''; b.appendChild(im);
      }
      var tx=document.createElement('div'); tx.className='tf-ep-txt';
      var tt=document.createElement('div'); tt.className='tf-ep-tt';
      var t1=document.createElement('span'); t1.textContent=e.nome||('Episodio '+(e.num||''));
      var t2=document.createElement('span'); t2.className='tf-ep-du'; t2.textContent=e.dur?(e.dur+' min'):'';
      tt.appendChild(t1); tt.appendChild(t2); tx.appendChild(tt);
      if(e.plot){ var pl=document.createElement('div'); pl.className='tf-ep-pl'; pl.textContent=e.plot; tx.appendChild(pl); }
      b.appendChild(tx);
      b.addEventListener('click', function(){ vaiEp(e, st.n); });
      lista.appendChild(b);
    });
  }
  function mostraStagioni(){
    var lista=$('eps-lista');
    $('eps-titolo').textContent='Stagioni';
    $('b-eps-back').style.display='none';
    clear(lista);
    var cur=posizioneCorrente()[0];
    EPS.forEach(function(st,i){
      var b=document.createElement('button'); b.className='tf-st'+(i===cur?' cur':'');
      var a=document.createElement('span'); a.textContent = st.n ? ('Stagione '+st.n) : 'Episodi';
      var c=document.createElement('span'); c.className='tf-st-ora';
      c.textContent = (i===cur?'in riproduzione · ':'')+st.eps.length+' episodi';
      b.appendChild(a); b.appendChild(c);
      b.addEventListener('click', function(){ mostraEpisodi(i); });
      lista.appendChild(b);
    });
  }
  function apriEps(){
    if(!EPS.length){ return; }
    closeMenus();
    mostraEpisodi(posizioneCorrente()[0]);
    $('eps').classList.add('open');
    var att=$('eps-lista').querySelector('.tf-ep.cur');
    if(att && att.scrollIntoView){ att.scrollIntoView({block:'center'}); }
    showUI();
  }
  function chiudiEps(){ $('eps').classList.remove('open'); }
  function epsAperto(){ return $('eps').classList.contains('open'); }

  // ---- costruzione menu ----
  function clear(el){ while(el.firstChild){ el.removeChild(el.firstChild); } }
  function mkOpt(label, active, onclick){
    var d=document.createElement('div'); d.className='tf-opt'+(active?' active':'');
    var dot=document.createElement('span'); dot.className='tf-dot';
    var t=document.createElement('span'); t.textContent=label;
    d.appendChild(dot); d.appendChild(t);
    d.addEventListener('click', function(ev){ ev.stopPropagation(); onclick(); });
    return d;
  }
  function buildAudio(){
    var el=$('m-audio'), sec=el.parentNode; clear(el);
    var tracks=(hls&&hls.audioTracks)?hls.audioTracks:[];
    if(tracks.length<1){ sec.style.display='none'; return; }
    sec.style.display='';
    tracks.forEach(function(tr,i){ el.appendChild(mkOpt(audioLabel(tr), hls.audioTrack===i, function(){ scegliAudio(i); })); });
  }
  function buildSubs(){
    var el=$('m-subs'), sec=el.parentNode; clear(el);
    var tracks=(hls&&hls.subtitleTracks)?hls.subtitleTracks:[];
    sec.style.display='';
    el.appendChild(mkOpt('Disattivati', !hls||hls.subtitleTrack<0, function(){ scegliSub(-1); }));
    tracks.forEach(function(tr,i){ el.appendChild(mkOpt(subLabel(tr), hls&&hls.subtitleTrack===i, function(){ scegliSub(i); })); });
  }
  function buildQuality(){
    var el=$('m-quality'), sec=el.parentNode; clear(el);
    var levels=(hls&&hls.levels)?hls.levels:[];
    if(levels.length<1){ sec.style.display='none'; return; }
    sec.style.display='';
    var auto=hls.autoLevelEnabled;
    var curH=(hls.currentLevel>=0&&levels[hls.currentLevel])?(levels[hls.currentLevel].height+'p'):'';
    el.appendChild(mkOpt('Auto'+(auto&&curH?(' ('+curH+')'):''), auto, function(){ scegliQual(-1); }));
    var idx=[]; levels.forEach(function(l,i){ idx.push({i:i,h:l.height||0}); });
    idx.sort(function(a,b){ return b.h-a.h; });
    idx.forEach(function(o){ el.appendChild(mkOpt((o.h||'?')+'p', !auto&&hls.currentLevel===o.i, function(){ scegliQual(o.i); })); });
  }
  function buildSpeed(){
    var el=$('m-speed'); clear(el);
    [0.5,0.75,1,1.25,1.5,2].forEach(function(r){ el.appendChild(mkOpt(r===1?'Normale':(r+'x'), Math.abs(v.playbackRate-r)<0.01, function(){ v.playbackRate=r; buildSpeed(); })); });
  }
  function buildAll(){ buildAudio(); buildSubs(); buildQuality(); buildSpeed(); }
  function anyMenuOpen(){ return menuAV.classList.contains('open')||menuQS.classList.contains('open')||menuCast.classList.contains('open'); }
  function closeMenus(){ menuAV.classList.remove('open'); menuQS.classList.remove('open'); menuCast.classList.remove('open'); }
  function placeMenu(el, btn){ var br=btn.getBoundingClientRect(); el.style.right=Math.max(8,(window.innerWidth-br.right))+'px'; }
  function toggleAV(){ var open=menuAV.classList.contains('open'); closeMenus(); if(!open){ buildAudio(); buildSubs(); placeMenu(menuAV,$('b-cc')); menuAV.classList.add('open'); } showUI(); }
  function toggleQS(){ var open=menuQS.classList.contains('open'); closeMenus(); if(!open){ buildQuality(); buildSpeed(); placeMenu(menuQS,$('b-gear')); menuQS.classList.add('open'); } showUI(); }

  // ---- sottotitoli on/off rapido ----
  function preferredSub(){
    var t=(hls&&hls.subtitleTracks)?hls.subtitleTracks:[];
    for(var i=0;i<t.length;i++){ var L=(t[i].lang||'').toLowerCase(); if(L.indexOf('it')===0&&!/forced/i.test(t[i].name||'')){ return i; } }
    return t.length?0:-1;
  }
  function toggleSubs(){
    if(!hls){ return; }
    if(hls.subtitleTrack>=0){ lastSub=hls.subtitleTrack; scegliSub(-1); }
    else { scegliSub(lastSub>=0?lastSub:preferredSub()); }
  }

  // ---- auto-hide controlli ----
  function showUI(){ tf.classList.remove('hide-ui'); scheduleHide(); }
  function scheduleHide(){ clearTimeout(hideTimer); hideTimer=setTimeout(function(){ if(!v.paused&&!anyMenuOpen()){ tf.classList.add('hide-ui'); } }, 3000); }
  tf.addEventListener('mousemove', showUI);
  tf.addEventListener('mouseleave', function(){ if(!v.paused&&!anyMenuOpen()){ tf.classList.add('hide-ui'); } });

  // ---- click sul video: play (singolo) / fullscreen (doppio) ----
  var clickT=null;
  v.addEventListener('click', function(){
    if(clickT){ clearTimeout(clickT); clickT=null; toggleFs(); }
    else { clickT=setTimeout(function(){ clickT=null; togglePlay(); }, 220); }
  });

  // ---- bottoni ----
  function seekBy(s){ if(v.duration){ v.currentTime=Math.max(0,Math.min(v.duration,v.currentTime+s)); } else { v.currentTime=Math.max(0,v.currentTime+s); } }
  $('bigplay').onclick=togglePlay; $('b-play').onclick=togglePlay;
  $('b-back').onclick=function(){ seekBy(-10); }; $('b-fwd').onclick=function(){ seekBy(10); };
  $('b-mute').onclick=toggleMute;
  $('b-dl').onclick=function(ev){ ev.stopPropagation(); scarica(); };
  $('b-cast').onclick=function(ev){ ev.stopPropagation(); toggleCast(); };
  $('b-eps').onclick=function(ev){ ev.stopPropagation(); if(epsAperto()){ chiudiEps(); } else { apriEps(); } };
  $('b-next').onclick=function(ev){ ev.stopPropagation(); var p=prossimoEp(); if(p){ vaiEp(p.e, p.s); } };
  $('b-eps-back').onclick=function(ev){ ev.stopPropagation(); mostraStagioni(); };
  $('b-eps-close').onclick=function(ev){ ev.stopPropagation(); chiudiEps(); };
  // click sulla zona scura = chiudi; stopPropagation per non mettere in pausa il video
  $('eps').addEventListener('click', function(ev){ ev.stopPropagation(); if(ev.target===$('eps')){ chiudiEps(); } });
  $('b-cc').onclick=function(ev){ ev.stopPropagation(); toggleAV(); };
  $('b-gear').onclick=function(ev){ ev.stopPropagation(); toggleQS(); };
  $('b-pip').onclick=togglePip; $('b-fs').onclick=toggleFs;
  document.addEventListener('click', function(e){ if(anyMenuOpen() && !menuAV.contains(e.target) && !menuQS.contains(e.target)){ closeMenus(); } });

  // ---- scorciatoie tastiera ----
  window.addEventListener('keydown', function(e){
    var k=e.key;
    if(k===' '||k==='k'||k==='K'){ e.preventDefault(); togglePlay(); showUI(); }
    else if(k==='f'||k==='F'){ toggleFs(); }
    else if(k==='m'||k==='M'){ toggleMute(); showUI(); }
    else if(k==='ArrowLeft'){ seekBy(-5); showUI(); }
    else if(k==='ArrowRight'){ seekBy(5); showUI(); }
    else if(k==='j'||k==='J'){ seekBy(-10); showUI(); }
    else if(k==='l'||k==='L'){ seekBy(10); showUI(); }
    else if(k==='ArrowUp'){ e.preventDefault(); setVol((v.muted?0:v.volume)+0.1); showUI(); }
    else if(k==='ArrowDown'){ e.preventDefault(); setVol((v.muted?0:v.volume)-0.1); showUI(); }
    else if(k==='c'||k==='C'){ toggleSubs(); showUI(); }
    else if(k>='0'&&k<='9'){ if(v.duration){ v.currentTime=v.duration*(parseInt(k,10)/10); } showUI(); }
    else if(k==='Escape'){ if(epsAperto()){ chiudiEps(); } else if(anyMenuOpen()){ closeMenus(); } }
  });

  // ---- auto-selezione audio italiano ----
  function autoItalian(){
    if(!hls||!hls.audioTracks){ return; }
    var idx=-1;
    hls.audioTracks.forEach(function(tr,i){ if(idx<0){ var L=(tr.lang||'').toLowerCase(), n=(tr.name||'').toLowerCase(); if(L.indexOf('it')===0||n.indexOf('ital')>=0){ idx=i; } } });
    if(idx>=0 && hls.audioTrack!==idx){ hls.audioTrack=idx; }
  }

  // ---- applica le preferenze ricordate ----
  // Due insidie risolte qui:
  //  1) a MANIFEST_PARSED le liste tracce sono spesso ANCORA VUOTE -> non si decide
  //     nulla e si ritenta quando hls annuncia le tracce (eventi *_UPDATED);
  //  2) subito dopo, hls RIMETTE la sua traccia predefinita (di solito i forzati) ->
  //     si riapplica la scelta anche su *_SWITCHED, con un tetto di tentativi per
  //     non litigare all'infinito.
  // Ogni impostazione resta indipendente: se la lingua preferita non c'e' si ripiega
  // sul default disponibile, ma le ALTRE vengono comunque applicate.
  var prefAudioFatto=false, tentAudio=0, tentSub=0;
  var MAX_TENT=6;

  function idxAudioVoluto(){
    var t=(hls&&hls.audioTracks)||[];
    if(!t.length||!PREF.audio){ return -1; }
    for(var i=0;i<t.length;i++){ if(trackLang(t[i])===PREF.audio){ return i; } }
    return -1;
  }
  function idxSubVoluto(){
    var t=(hls&&hls.subtitleTracks)||[];
    if(!PREF.sub||PREF.sub==='off'){ return -1; }   // mai scelti o spenti apposta
    if(!t.length){ return -2; }                     // non ancora pronti: riprova dopo
    var i;
    // prima il nome esatto (distingue "English [CC]" dai forzati), poi la lingua
    if(PREF.subname){ for(i=0;i<t.length;i++){ if((t[i].name||'')===PREF.subname){ return i; } } }
    for(i=0;i<t.length;i++){ if(trackLang(t[i])===PREF.sub){ return i; } }
    return -1;                                      // lingua non disponibile -> spenti
  }

  function applyAudioPref(){
    if(!hls||tentAudio>MAX_TENT){ return; }
    var t=hls.audioTracks||[];
    if(!t.length){ return; }                        // tracce non ancora annunciate
    var idx=idxAudioVoluto();
    if(idx<0){                                      // preferita assente -> italiano se c'e'
      if(!prefAudioFatto){ prefAudioFatto=true; autoItalian(); }
      return;
    }
    prefAudioFatto=true;
    if(hls.audioTrack!==idx){ tentAudio++; hls.audioTrack=idx; }
  }
  function applySubPref(){
    if(!hls||tentSub>MAX_TENT){ return; }
    var idx=idxSubVoluto();
    if(idx===-2){ return; }                         // lista non ancora pronta
    if(hls.subtitleTrack!==idx){ tentSub++; hls.subtitleTrack=idx; }
  }
  function applyQualPref(){
    if(!hls||!PREF.qual||PREF.qual==='auto'){ return; }
    var h=parseInt(PREF.qual,10); if(!h){ return; }
    var levels=hls.levels||[], idx=-1;
    levels.forEach(function(l,i){ if(l.height===h){ idx=i; } });
    if(idx>=0){ hls.currentLevel=idx; }             // altrimenti resta Auto
  }
  function applyPrefs(){ applyAudioPref(); applySubPref(); applyQualPref(); }

  // ---- ripresa posizione (continua a guardare) ----
  // L'iframe ha origine opaca (niente localStorage utile): il minuto si invia
  // al server-ponte con sendBeacon, e si riparte da __STARTAT__ dato da Python.
  var STARTAT = parseFloat("__STARTAT__") || 0;
  function savePos(){
    if(!RKEY || !v.duration || !isFinite(v.duration)){ return; }
    var p = (v.currentTime >= v.duration - 5) ? 0 : v.currentTime;  // se finito, azzera
    try{
      // "beacon" via GET di immagine: e' un semplice caricamento risorsa cross-origin
      // (come i segmenti video) e funziona anche dall'iframe a origine opaca.
      var u = "http://localhost:8765/pos?key=" + encodeURIComponent(RKEY) +
              "&p=" + Math.floor(p) + "&d=" + Math.floor(v.duration) + "&_=" + Date.now();
      var img = new Image();
      img.src = u;
    }catch(e){}
  }
  var resumed=false;
  v.addEventListener('loadedmetadata', function(){
    if(resumed){ return; } resumed=true;
    if(STARTAT>30 && v.duration && STARTAT < v.duration*0.97){ try{ v.currentTime=STARTAT; }catch(e){} }
  });
  setInterval(savePos, 5000);
  v.addEventListener('pause', savePos);
  window.addEventListener('beforeunload', savePos);
  window.addEventListener('pagehide', savePos);

  // ---- fallback nativo ----
  function nativeFallback(){ try{ if(hls){ hls.destroy(); hls=null; } }catch(e){} v.src=SRC; v.play().catch(showBigPlay); }
  function showBigPlay(){ tf.classList.add('is-paused'); tf.classList.remove('buffering'); paintPlay(); }

  // ---- tracce native (per i file locali offline) ----
  function buildNativeSubs(){
    var el=$('m-subs'), sec=el.parentNode; clear(el);
    var tt=v.textTracks||[];
    if(tt.length<1){ sec.style.display='none'; return; }
    sec.style.display='';
    var anyShow=false;
    for(var i=0;i<tt.length;i++){ if(tt[i].mode==='showing'){ anyShow=true; } }
    el.appendChild(mkOpt('Disattivati', !anyShow, function(){ for(var j=0;j<tt.length;j++){ tt[j].mode='disabled'; } buildNativeSubs(); }));
    Array.prototype.forEach.call(tt, function(t,i){
      el.appendChild(mkOpt(t.label||t.language||('Traccia '+(i+1)), t.mode==='showing', function(){
        for(var j=0;j<tt.length;j++){ tt[j].mode = (j===i)?'showing':'disabled'; } buildNativeSubs();
      }));
    });
  }
  function buildNativeAudio(){
    var el=$('m-audio'), sec=el.parentNode; clear(el);
    var at=v.audioTracks;   // Chrome NON la espone (resta vuoto): limite del browser
    if(!at || at.length<2){ sec.style.display='none'; return; }
    sec.style.display='';
    Array.prototype.forEach.call(at, function(t,i){
      el.appendChild(mkOpt(t.label||t.language||('Audio '+(i+1)), t.enabled, function(){
        for(var j=0;j<at.length;j++){ at[j].enabled = (j===i); } buildNativeAudio();
      }));
    });
  }
  function buildNativeTracks(){ buildNativeSubs(); buildNativeAudio(); }

  // ---- avvio ----
  function start(){
    paintPlay(); paintVol(); paintFs(); setVol(1);
    if(ISFILE){
      // file locale (offline): riproduzione nativa, niente HLS
      v.src=SRC;
      $('m-quality').parentNode.style.display='none';   // niente livelli per un file
      v.addEventListener('loadedmetadata', function(){ buildSpeed(); buildNativeTracks(); });
      v.addEventListener('loadeddata', buildNativeTracks);
      if(v.textTracks && v.textTracks.addEventListener){ v.textTracks.addEventListener('addtrack', buildNativeTracks); }
      if(v.audioTracks && v.audioTracks.addEventListener){ v.audioTracks.addEventListener('addtrack', buildNativeTracks); }
      setTimeout(buildNativeTracks, 1200);
      v.play().then(function(){ tf.classList.remove('buffering'); }).catch(showBigPlay);
      return;
    }
    if(window.Hls && Hls.isSupported()){
      hls=new Hls({ enableWorker:true, lowLatencyMode:false, maxBufferLength:30, backBufferLength:60,
        subtitleDisplay:true, fragLoadingMaxRetry:6, manifestLoadingMaxRetry:4, levelLoadingMaxRetry:4 });
      hls.on(Hls.Events.MANIFEST_PARSED, function(){
        applyPrefs();
        buildAll();
        // rete di sicurezza: se qualche traccia arriva senza eventi utili, riprova
        setTimeout(function(){ applyAudioPref(); applySubPref(); buildAll(); }, 800);
        setTimeout(function(){ applyAudioPref(); applySubPref(); buildAll(); }, 2500);
        v.play().then(function(){ tf.classList.remove('buffering'); }).catch(showBigPlay);
      });
      hls.on(Hls.Events.AUDIO_TRACKS_UPDATED, function(){ applyAudioPref(); buildAudio(); });
      hls.on(Hls.Events.AUDIO_TRACK_SWITCHED, function(){ applyAudioPref(); buildAudio(); });
      hls.on(Hls.Events.LEVEL_SWITCHED, buildQuality);
      hls.on(Hls.Events.SUBTITLE_TRACKS_UPDATED, function(){ applySubPref(); buildSubs(); });
      hls.on(Hls.Events.SUBTITLE_TRACK_SWITCHED, function(){ applySubPref(); buildSubs(); });
      hls.on(Hls.Events.SUBTITLE_TRACK_LOADED, function(){ applySubPref(); buildSubs(); });
      hls.on(Hls.Events.ERROR, function(e, data){
        if(!data || !data.fatal){ return; }
        if(data.type===Hls.ErrorTypes.NETWORK_ERROR){ try{ hls.startLoad(); }catch(x){ nativeFallback(); } }
        else if(data.type===Hls.ErrorTypes.MEDIA_ERROR){ try{ hls.recoverMediaError(); }catch(x){ nativeFallback(); } }
        else { nativeFallback(); }
      });
      hls.loadSource(SRC);
      hls.attachMedia(v);
    } else if(v.canPlayType('application/vnd.apple.mpegurl')){
      v.src=SRC;
      v.addEventListener('loadedmetadata', function(){ buildSpeed(); });
      v.play().then(function(){ tf.classList.remove('buffering'); }).catch(showBigPlay);
    } else {
      v.src=SRC; v.controls=true;
    }
  }
  if(document.readyState!=='loading'){ start(); } else { document.addEventListener('DOMContentLoaded', start); }
})();
</script>
</body></html>
"""


def mostra_player(m3u8, titolo="", resume_key="", is_file=False, pref_key="", episodi=None,
                  ep_corrente="", dl_stato="no", cast_dev=None, cast_scan=False, castabile=False):
    if not m3u8:
        st.error("❌ Flusso non disponibile per questo titolo. Riprova o scegli un altro episodio.")
        return
    t_safe = (titolo or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    rk_safe = (resume_key or "").replace('"', "").replace("\\", "")
    pos = posizione(resume_key) if resume_key else None
    start_at = str(int(pos["p"])) if (pos and pos.get("p", 0) > 30) else "0"
    # preferenze di questa serie (o le ultime usate in assoluto se e' la prima volta)
    pref = preferenze(pref_key)
    def _js(x):
        return str(x if x is not None else "").replace("\\", "").replace('"', "")
    html = (_PLAYER_HTML.replace("__SRC__", m3u8)
            .replace("__TITLE__", t_safe).replace("__RESUMEKEY__", rk_safe)
            .replace("__STARTAT__", start_at).replace("__ISFILE__", "1" if is_file else "0")
            .replace("__PREFKEY__", _js(pref_key))
            .replace("__PREFAUDIO__", _js(pref.get("audio")))
            .replace("__PREFSUB__", _js(pref.get("sub")))
            .replace("__PREFSUBNAME__", _js(pref.get("subname")))
            .replace("__PREFQUAL__", _js(pref.get("qual")))
            # episodi per il popup: JSON gia' pronto (l'iframe non puo' chiederli a runtime).
            # "</" va spezzato o chiuderebbe il tag <script>.
            .replace("__EPISODI__", json.dumps(episodi or [], ensure_ascii=False).replace("</", "<" + chr(92) + "/"))
            .replace("__EPCORR__", _js(ep_corrente))
            .replace("__DLSTATO__", _js(dl_stato))
            .replace("__CASTDEV__", json.dumps(cast_dev or [], ensure_ascii=False).replace("</", "<" + chr(92) + "/"))
            .replace("__CASTSCAN__", "1" if cast_scan else "0")
            .replace("__CASTABILE__", "1" if castabile else "0"))
    components.html(html, height=648)
    st.caption("🗨 Icona sottotitoli = **audio** (IT/originale) + **sottotitoli**.  ⏱ Icona contagiri = **qualità** (480/720/1080) + **velocità**. "
               "Scorciatoie: spazio/k play, j/l ±10s, ←/→ ±5s, m muto, c sottotitoli, f schermo intero.  "
               "💾 Quello che scegli resta **predefinito per questa serie** (e per i prossimi titoli).")


def _cambia_episodio(src, richiesta):
    """Esegue la richiesta arrivata dal player (episodio scelto nel popup o tasto
    'prossimo episodio'). Il player puo' solo mandare il beacon: il flusso lo recupera
    qui Python, poi si riparte con lo stesso meccanismo di sempre."""
    ep_id = richiesta.get("ep")
    stagione = richiesta.get("s") or None
    numero = richiesta.get("n") or None
    if not (src and ep_id):
        return
    with st.spinner("Carico l'episodio…"):
        if src.get("provider") == "sc":
            link = _flusso_sc(src["id"], src.get("slug"), ep_id, stagione, numero)
        else:
            link = au.m3u8_episodio(ep_id, au_base())
    if not link:
        st.error("Non riesco a caricare quell'episodio. Riprova.")
        return
    elemento = {"provider": src.get("provider"), "id": src.get("id"), "slug": src.get("slug"),
                "type": src.get("type"), "uid": src.get("uid"), "name": src.get("name"),
                "poster": src.get("poster"), "landscape": src.get("landscape"),
                "anilist_id": src.get("anilist_id")}
    et = (f"S{stagione}E{numero}" if stagione else (f"Ep {numero}" if numero else "Episodio"))
    riproduci(link, f"{src.get('name')} · {et}", elemento,
              {"id": ep_id, "season": stagione, "number": numero},
              torna=st.session_state.get("player_torna", "dettaglio"))
    st.rerun()


def _nome_download(titolo):
    """Nome cartella del download: la qualita' e' sempre la massima (1080p)."""
    return _safe_name(titolo) + " [1080p]"


def _esegui_azione(src, azione, dato):
    """Esegue quello che il player ha chiesto (scarica / cast). Il player manda solo un
    beacon: qui c'e' il contesto (flusso, titolo, meta) per farlo davvero."""
    if not src:
        return
    if azione == "scarica":
        nome = _nome_download(st.session_state.get("titolo_player", ""))
        if dm.gia_in_coda(nome):
            st.toast("Questo video è già scaricato o in download.")
            return
        with st.spinner("Preparo il download…"):
            master = _master_fresco(src)
        if not master:
            st.error("Flusso non disponibile per il download. Riprova.")
            return
        meta = {"uid": src.get("uid"), "name": src.get("name"), "type": src.get("type"),
                "poster": src.get("poster"), "landscape": src.get("landscape"),
                "anilist_id": src.get("anilist_id"), "provider": src.get("provider"),
                "id": src.get("id"), "slug": src.get("slug"), "ep_id": src.get("ep_id"),
                "season": src.get("season"), "number": src.get("number"),
                "ep_label": src.get("ep_label"), "resume_key": st.session_state.get("resume_key", "")}
        # massima qualita' + tutte le tracce audio/sottotitoli, senza chiedere nulla
        dm.avvia_download(master, nome, 1080, st.session_state.get("titolo_player", ""), meta, True)
        st.toast("⬇ Download avviato — stato in Home › 📥 Download")
        return
    if azione == "cast-scan":
        with st.spinner("Cerco dispositivi nella rete…"):
            casting.scopri()
        return
    if azione == "cast-stop":
        casting.ferma()
        st.toast("Trasmissione interrotta.")
        return
    if azione == "cast" and dato:
        url = st.session_state.get("m3u8")
        if not url:
            return
        inizio = 0.0
        p = posizione(st.session_state.get("resume_key", ""))
        if p and p.get("p"):
            inizio = float(p["p"])          # riprende dal minuto gia' visto
        with st.spinner(f"Avvio su «{dato}»…"):
            ok, msg = casting.trasmetti(dato, url, st.session_state.get("titolo_player", ""), inizio)
        st.toast(("📺 " if ok else "❌ ") + msg)


@st.fragment(run_every=1)
def _ascolta_player():
    """Il player e' un iframe a origine opaca: puo' solo INVIARE richieste (beacon verso
    il ponte). Qui si controlla ogni secondo se ne e' arrivata una nuova."""
    r = leggi_vai()
    if r and r.get("ep") and r.get("t") != st.session_state.get("ultimo_vai_t"):
        st.session_state.ultimo_vai_t = r.get("t")
        st.session_state.vai_pendente = r
        st.rerun(scope="app")
    a = leggi_azione()
    if a and a.get("a") and a.get("t") != st.session_state.get("ultima_azione_t"):
        st.session_state.ultima_azione_t = a.get("t")
        st.session_state.azione_pendente = a
        st.rerun(scope="app")


@st.cache_data(ttl=1800, show_spinner=False)
def _dati_episodi(provider, tid, slug, uid):
    """Tutte le stagioni con i loro episodi, per il popup episodi DENTRO il player.

    Perche' tutto in una volta: il player e' un iframe a origine opaca e Chrome gli blocca
    sia `fetch` sia il caricamento di script da localhost (Private Network Access) - puo'
    solo INVIARE beacon. Quindi non puo' chiedere dati a runtime: dev'essere gia' tutto
    iniettato. Le stagioni si scaricano IN PARALLELO (1 richiesta ciascuna) e il risultato
    resta in cache, cosi' il costo si paga una volta sola e sfogliare le stagioni mentre
    guardi non interrompe il video."""
    import concurrent.futures as _cf
    try:
        if provider == "sc":
            nums = [n for n in (sc.stagioni(tid, slug) or []) if n]
            if not nums:
                return []
            with _cf.ThreadPoolExecutor(max_workers=min(6, len(nums))) as ex:
                coppie = list(ex.map(lambda n: (n, sc.episodi(tid, slug, n)), nums))
            fuori = []
            for n, eps in sorted(coppie, key=lambda c: _num(c[0])):
                voci = [{"id": str(e["id"]), "num": str(e.get("number") or ""),
                         "nome": e.get("name") or "", "img": e.get("image") or "",
                         "dur": e.get("duration") or 0,
                         "plot": (e.get("plot") or "")[:200]} for e in (eps or [])]
                if voci:
                    fuori.append({"n": str(n), "eps": voci})
            return fuori
        if provider == "au":
            base = au_base()
            eps = au.episodi(tid, slug, base) if base else []
            voci = [{"id": str(e["id"]), "num": str(e.get("number") or ""),
                     "nome": "", "img": "", "dur": 0, "plot": ""} for e in (eps or [])]
            return [{"n": "", "eps": voci}] if voci else []
    except Exception:
        return []
    return []


def _num(x):
    try:
        return float(x)
    except Exception:
        return 0.0


def _flusso_sc(title_id, slug=None, ep_id=None, season=None, number=None):
    """Flusso di un titolo StreamingCommunity, con SORGENTE ALTERNATIVA.

    Prova prima **VixSrc**: e' un frontend pubblico sulla STESSA libreria vixcloud (stessi
    video id), ma il suo token concede l'FHD (`canPlayFHD=1`) mentre SC da anonimo no. Oggi
    film e serie sono comunque codificati a 480/720, quindi la qualita' non cambia; serve per
    due cose: se rimettono le codifiche 1080p le prendiamo in automatico, ed e' una seconda
    strada verso lo stesso video quando il frontend SC fa i capricci (dominio ruotato, ecc.).
    Se VixSrc non ha il titolo o non risponde, si ripiega su SC senza che l'utente noti nulla.
    L'm3u8 ha la stessa struttura (CORS *, tracce audio/sottotitoli), quindi il player e le
    preferenze funzionano identici."""
    if not (ep_id and not number):      # per un episodio senza numero VixSrc non sa cosa servire
        try:
            tid = sc.tmdb_id(title_id, slug)
            if tid:
                link = vixsrc.m3u8(tid, season, number) if ep_id else vixsrc.m3u8(tid)
                if link:
                    return link
        except Exception:
            pass
    return sc.m3u8(title_id, ep_id)


def _master_fresco(src):
    """Ri-ottiene un m3u8 master fresco (token nuovo) per il download."""
    if not src:
        return None
    if src.get("provider") == "sc":
        return _flusso_sc(src["id"], src.get("slug"), src.get("ep_id"),
                          src.get("season"), src.get("number"))
    if src.get("provider") == "au":
        return au.m3u8_episodio(src.get("ep_id"), au_base())
    return None


# ── Ricerca CROSS-GENRE (Film + Serie + Anime insieme) ───────────────────
def cerca_tutto(query):
    """Cerca su StreamingCommunity (film+serie) E AnimeUnity (anime), unisce e
    ordina per pertinenza. Ogni fonte è isolata: se una va in errore, le altre restano."""
    out = []
    try:
        for r in sc.cerca(query):
            if r.get("type") not in ("movie", "tv"):
                continue
            out.append({"provider": "sc", "id": r["id"], "slug": r["slug"], "name": r["name"],
                        "poster": r.get("poster"), "landscape": r.get("landscape"), "type": r["type"],
                        "voto": r.get("score"), "year": r.get("year"), "seasons": r.get("seasons"),
                        "uid": f"sc:{r['id']}"})
    except Exception:
        pass
    try:
        base = au_base()
        if base:
            for r in au.cerca(query, base):
                # titoli alternativi (romaji/eng/it): AnimeUnity li espone, servono perché
                # cercando "Attack on Titan" l'anime si chiama "Shingeki no Kyojin" (vedi _relevanza_item)
                alt = [t for t in (r.get("title"), r.get("title_eng"),
                                   r.get("title_it"), r.get("title_jp")) if t]
                out.append({"provider": "au", "id": r["id"], "slug": r["slug"], "name": r["title"],
                            "poster": r.get("poster"), "landscape": r.get("landscape"), "type": "anime",
                            "plot": r.get("plot", ""), "dub": r.get("dub"), "uid": f"au:{r['id']}",
                            "alt": alt, "anilist_id": r.get("anilist_id")})
    except Exception:
        pass
    _arricchisci_anime(out)
    return _ordina_pertinenza(out, query)


def _arricchisci_anime(items):
    """Per gli anime usa le immagini AniList (vere e uniformi), via anilist_id (batch+cache):
    POSTER = copertina verticale (per le card), LANDSCAPE = banner (per il banner del dettaglio).
    L'immagine di AnimeUnity a volte è inaffidabile. Modifica gli item sul posto."""
    anime = [it for it in items if it.get("type") == "anime"]
    ids = [it.get("anilist_id") for it in anime if it.get("anilist_id")]
    if not ids:
        return
    try:
        info = anilist.info(ids)
    except Exception:
        info = {}
    for it in anime:
        rec = info.get(int(it["anilist_id"])) if it.get("anilist_id") else None
        if not rec:
            continue
        if rec.get("cover"):
            it["poster"] = rec["cover"]                     # copertina verticale vera → card
        if rec.get("banner"):
            it["landscape"] = rec["banner"]                 # banner orizzontale → dettaglio


def _relevanza(nome, q_l, q_tokens):
    """Punteggio di pertinenza di un titolo rispetto al cerca. -1 = nessun match (rumore)."""
    n = (nome or "").lower()
    if not q_tokens:
        return 0.0
    matched = sum(1 for t in q_tokens if t in n)
    if matched == 0:
        return -1.0
    score = matched / len(q_tokens) * 10.0   # quante parole del cerca compaiono
    if q_l in n:
        score += 20.0                         # contiene la frase intera
    if n.startswith(q_l):
        score += 10.0                         # inizia con la frase
    if n == q_l:
        score += 40.0                         # titolo esatto
    return score


def _relevanza_item(it, q_l, q_tokens):
    """Pertinenza di un item considerando TUTTI i suoi titoli (nome + alternativi).
    Così "Attack on Titan" matcha l'anime "Shingeki no Kyojin" (alt title eng)."""
    titoli = it.get("alt") or [it.get("name")]
    return max((_relevanza(t, q_l, q_tokens) for t in titoli), default=-1.0)


def _ordina_pertinenza(items, query):
    """Filtra i risultati senza alcuna parola del cerca e ordina per pertinenza.
    Se la query "è un anime" (un anime matcha bene almeno quanto il miglior film/serie),
    gli anime vanno in cima. A parità, ordine alfabetico (raggruppa sub/ita e i franchise)."""
    q_l = query.strip().lower()
    q_tokens = [t for t in re.split(r"\W+", q_l) if t]
    scored = []
    for it in items:
        r = _relevanza_item(it, q_l, q_tokens)
        if r >= 0:
            scored.append((r, it))
    # la query "punta a un anime"? (un anime matcha tutti i token e bene quanto il resto)
    rel_anime = max((r for r, it in scored if it.get("type") == "anime"), default=-1.0)
    rel_altro = max((r for r, it in scored if it.get("type") != "anime"), default=-1.0)
    anime_query = rel_anime >= 10.0 and rel_anime >= rel_altro

    def chiave(pair):
        r, it = pair
        anime_first = 1 if (anime_query and it.get("type") == "anime") else 0
        return (-anime_first, -r, (it.get("name") or "").lower())

    scored.sort(key=chiave)
    return [it for (_, it) in scored]


def _resume_key(uid, ep_id=None):
    return f"{uid}:{ep_id}" if ep_id else str(uid)


def _ep_label(tipo, ep):
    if tipo == "movie":
        return "Film"
    if ep.get("season") and ep.get("number"):
        return f"S{ep['season']}E{ep['number']}"
    if ep.get("number"):
        return f"Ep {ep['number']}"
    return "Episodio"


def riproduci(m3u8, titolo, elemento, ep=None, torna="dettaglio"):
    st.session_state.m3u8 = m3u8
    st.session_state.titolo_player = titolo
    st.session_state.is_offline = False
    st.session_state.offline_is_file = False
    st.session_state.player_torna = torna   # dove torna il tasto "indietro" del player
    uid = elemento["uid"]
    ep = ep or {}
    ep_id = ep.get("id")
    rkey = _resume_key(uid, ep_id)
    st.session_state.resume_key = rkey
    # contesto per ri-scaricare / riprendere lo stesso episodio
    st.session_state.play_src = {
        "provider": elemento.get("provider"), "id": elemento.get("id"), "slug": elemento.get("slug"),
        "type": elemento.get("type"), "uid": uid, "ep_id": ep_id, "name": elemento.get("name"),
        "poster": elemento.get("poster"), "landscape": elemento.get("landscape"),
        "anilist_id": elemento.get("anilist_id"),
        "season": ep.get("season"), "number": ep.get("number"),
        "titolo": titolo, "ep_label": _ep_label(elemento.get("type"), ep),
    }
    # recente arricchito = "continua a guardare" (un'entry per titolo, con ultimo episodio)
    el = dict(elemento); el["tmdb_id"] = uid
    el["last"] = {"ep_id": ep_id, "season": ep.get("season"), "number": ep.get("number"),
                  "titolo": titolo, "resume_key": rkey}
    aggiungi_recente(el)
    vai("player")


def _validi(lista):
    # tiene solo gli item del nuovo modello (provider + name + uid)
    return [x for x in lista if x.get("provider") and x.get("name") and x.get("uid")]


def riprendi(item):
    """Riapre l'ultimo episodio visto di 'item' e fa riprendere il player dal minuto salvato."""
    last = item.get("last") or {}
    prov = item.get("provider")
    link, ep = None, None
    with st.spinner("Riprendo…"):
        if prov == "sc" and item.get("type") == "movie":
            link = _flusso_sc(item["id"], item.get("slug"))
        elif prov == "sc":
            link = _flusso_sc(item["id"], item.get("slug"), last.get("ep_id"),
                              last.get("season"), last.get("number"))
            ep = {"id": last.get("ep_id"), "season": last.get("season"), "number": last.get("number")}
        elif prov == "au":
            base = au_base()
            if base and last.get("ep_id"):
                link = au.m3u8_episodio(last.get("ep_id"), base)
            ep = {"id": last.get("ep_id"), "number": last.get("number")}
    if not link:
        st.error("Non riesco a riprendere: riaprilo dai dettagli.")
        return
    # "Continua a guardare" parte dalla home: il tasto indietro del player torna alla HOME
    # (non a una scheda dettaglio rimasta in memoria da una visita precedente).
    st.session_state.sel = item
    riproduci(link, last.get("titolo") or item.get("name"), item, ep, torna="home")
    st.rerun()


def _progress_frac(resume_key):
    p = posizione(resume_key)
    if p and p.get("d"):
        return max(0.0, min(1.0, p["p"] / p["d"]))
    return 0.0


def _prossimo_episodio(src):
    """Episodio successivo a quello in riproduzione (o None: film / ultimo episodio).
    Ritorna {id, season, number}. A fine stagione (SC) passa alla stagione dopo."""
    if not src or src.get("type") == "movie" or not src.get("ep_id"):
        return None
    prov, tid, slug, cur, season = (src.get("provider"), src.get("id"), src.get("slug"),
                                    src.get("ep_id"), src.get("season"))
    try:
        if prov == "sc":
            eps = _episodi_sc(tid, slug, season)
            ids = [e["id"] for e in eps]
            if cur in ids:
                i = ids.index(cur)
                if i + 1 < len(eps):
                    e = eps[i + 1]
                    return {"id": e["id"], "season": season, "number": e["number"]}
                stag = sc.stagioni(tid, slug)      # fine stagione -> 1° episodio della successiva
                if season in stag and stag.index(season) + 1 < len(stag):
                    ns = stag[stag.index(season) + 1]
                    ne = _episodi_sc(tid, slug, ns)
                    if ne:
                        return {"id": ne[0]["id"], "season": ns, "number": ne[0]["number"]}
        elif prov == "au":
            base = au_base()
            eps = au.episodi(tid, slug, base) if base else []
            ids = [e["id"] for e in eps]
            if cur in ids and ids.index(cur) + 1 < len(eps):
                e = eps[ids.index(cur) + 1]
                return {"id": e["id"], "season": None, "number": e["number"]}
    except Exception:
        pass
    return None


def render_continua(items):
    """'Continua a guardare' come UNICA riga orizzontale scorribile (stile Netflix)."""
    with st.container(key="continua_row"):
        cols = st.columns(max(1, len(items)))
        for col, it in zip(cols, items):
            with col:
                last = it.get("last") or {}
                rk = last.get("resume_key") or it.get("uid")
                if it.get("poster"):
                    st.image(it["poster"], use_container_width=True)
                st.markdown(f"**{it['name']}**")
                et = {"movie": "🎬 Film", "tv": "📺 Serie", "anime": "🌸 Anime"}.get(it.get("type"), "")
                if last.get("season") and last.get("number"):
                    lbl = f"{et} · S{last['season']}E{last['number']}"
                elif last.get("number"):
                    lbl = f"{et} · Ep {last['number']}"
                else:
                    lbl = et
                st.caption(lbl)
                frac = _progress_frac(rk)
                if frac > 0.01:
                    st.progress(frac)
                if st.button("▶ Riprendi", type="primary",
                             key=f"cont_{it['uid']}", use_container_width=True):
                    riprendi(it)


def guarda_offline(ep, voce):
    """Riproduce un episodio scaricato (servito dal ponte locale)."""
    st.session_state.m3u8 = bridge.url_file(ep["file"])
    st.session_state.titolo_player = ep.get("titolo") or voce.get("name")
    st.session_state.resume_key = ep.get("resume_key") or ""
    st.session_state.is_offline = True
    # nuovo formato = HLS locale (.m3u8 -> hls.js); vecchi download = .mp4 -> player nativo
    st.session_state.offline_is_file = not str(ep.get("file", "")).endswith(".m3u8")
    st.session_state.play_src = None
    vai("player")
    st.rerun()


@st.fragment(run_every=3)
def render_download_tab():
    """Stato download + libreria, auto-aggiornati ogni 3s (così i completati
    compaiono subito tra gli scaricati senza riavviare)."""
    st.markdown("#### ⏳ Download in corso")
    _render_download_attivi()
    st.markdown("#### 📂 Scaricati (guardabili offline)")
    render_libreria()


def _render_download_attivi():
    jobs = dm.lista_job()
    if not jobs:
        st.caption("Nessun download. Avvia un download dal player (⬇ sotto il video).")
        return
    attivi = [j for j in jobs if j["stato"] == "in corso"]
    for j in attivi:
        c1, c2 = st.columns([6, 1])
        c1.markdown(f"**{j['titolo']}** — {j['msg']}")
        c1.progress(min(1.0, j["frac"]))
        if c2.button("✖ Annulla", key=f"ann_{j['id']}"):
            dm.annulla(j["id"])
            st.rerun(scope="fragment")
    # in coda (partiranno uno alla volta dopo quello in corso), il prossimo = #1
    incoda = sorted([j for j in jobs if j["stato"] == "in coda"], key=lambda x: x["ts"])
    for pos, j in enumerate(incoda, 1):
        c1, c2 = st.columns([6, 1])
        c1.markdown(f"**{j['titolo']}** — 🕓 in coda (#{pos})")
        if c2.button("✖ Annulla", key=f"ann_{j['id']}"):
            dm.annulla(j["id"])
            st.rerun(scope="fragment")
    for j in [j for j in jobs if j["stato"] not in ("in corso", "in coda")]:
        c1, c2 = st.columns([6, 1])
        if j["stato"] == "completato":
            c1.success(f"✅ {j['titolo']} — scaricato")
        elif j["stato"] == "annullato":
            c1.info(f"⏹ {j['titolo']} — annullato")
        else:
            c1.error(f"❌ {j['titolo']} — {j.get('errore') or 'errore'}")
        if c2.button("OK", key=f"ok_{j['id']}"):
            dm.rimuovi_job(j["id"])
            st.rerun(scope="fragment")


def _poster_download(voce):
    """Locandina verticale (piccola) per un download: per gli anime preferisce la copertina
    AniList (via anilist_id, in cache); altrimenti il poster salvato col download."""
    if voce.get("provider") == "au" and voce.get("anilist_id"):
        try:
            rec = anilist.info([voce["anilist_id"]]).get(int(voce["anilist_id"]))
            if rec and rec.get("cover"):
                return rec["cover"]
        except Exception:
            pass
    return voce.get("poster") or voce.get("landscape")


def render_libreria():
    """Film/serie scaricati, con episodi, riproduzione offline ed eliminazione."""
    lib = dm.leggi_libreria()
    if not lib:
        st.info("Nessun video scaricato. Dal player usa **⬇ Scarica**.")
        return
    with st.container(key="dl_lib"):
      for uid, voce in lib.items():
        with st.container(border=True):
            c0, c1 = st.columns([1, 6])
            img = _poster_download(voce)
            if img:
                c0.image(img, use_container_width=True)
            with c1:
                st.markdown(f"**{voce.get('name')}**")
                for ep in voce.get("episodi", []):
                    esiste = dm.file_esiste(ep["file"])
                    e1, e2, e3, e4 = st.columns([2.6, 1.2, 1.2, 0.7])
                    e1.write(ep.get("label") + ("" if esiste else "  ⚠ file mancante"))
                    if esiste and e2.button("▶ Guarda", key=f"play_{ep['file']}", use_container_width=True):
                        guarda_offline(ep, voce)
                    if esiste and e3.button("⬇ MKV", key=f"mkv_{ep['file']}", use_container_width=True,
                                            help="Converte in un unico file .mkv (audio e sottotitoli inclusi)"):
                        with st.spinner("Converto in MKV (mux, può richiedere un po')…"):
                            ok, res = dm.esporta_mkv(ep["file"])
                        if ok:
                            st.toast("✅ MKV salvato: " + os.path.basename(res))
                        else:
                            st.toast("❌ MKV non riuscito: " + res)
                    if e4.button("🗑", key=f"del_{ep['file']}", use_container_width=True):
                        dm.elimina_episodio(uid, ep["file"])
                        st.rerun()


# ── Home stile Netflix: caroselli orizzontali (componente bidirezionale) ──
# Le card sono un componente Streamlit servito da home_component/index.html:
# il click manda l'uid a Python via Streamlit.setComponentValue -> niente polling,
# niente indicatore "in esecuzione" perenne.
_NETFLIX_HOME = components.declare_component(
    "tf_netflix_home", path=os.path.join(_BASE, "home_component"))


# Generi mostrati come righe della home, con ID HARDCODED (stabili su SC) così non serve
# una seconda sc.home() per risolverli. Pochi: SC STROZZA le richieste parallele
# (3 insieme ≈ 1.9s; 6 insieme ≈ 5.7s). Se un ID cambiasse, per_genere torna [] (riga assente).
_GENERI_HOME = [("Azione", 4), ("Commedia", 12), ("Horror", 7)]


@st.cache_data(ttl=600, show_spinner=False)
def _home_sliders():
    """PARTE VELOCE (mostrata subito): solo gli slider della homepage SC. ~1 richiesta."""
    try:
        rows, _gen = sc.home()
        return rows
    except Exception:
        return []


@st.cache_data(ttl=600, show_spinner=False)
def _home_extra():
    """PARTE LENTA (carica mentre l'utente esplora): righe per genere (SC) + righe anime (AU),
    in parallelo. Ritorna {'generi': [...], 'anime': [...]}."""
    import concurrent.futures as _cf

    def _generi():
        def _g(par):
            n, gid = par
            try:
                return n, sc.per_genere(gid, sort="views")
            except Exception:
                return n, []
        gen = []
        with _cf.ThreadPoolExecutor(max_workers=3) as ex2:   # poca concorrenza: SC strozza
            for n, items in ex2.map(_g, _GENERI_HOME):       # conserva l'ordine
                if items:
                    gen.append((n, items))
        return gen

    def _anime():
        try:                                      # i poster AU sono già verticali -> niente AniList qui
            base = au_base()
            return au.home(base) if base else []
        except Exception:
            return []

    with _cf.ThreadPoolExecutor(max_workers=2) as ex:
        fg, fa = ex.submit(_generi), ex.submit(_anime)
        return {"generi": fg.result(), "anime": fa.result()}


def _meta_card(score, year):
    """Riga piccola sotto la card: voto · anno."""
    return " · ".join([p for p in [(f"⭐ {score}" if score else None),
                                   (str(year) if year else None)] if p])


def _riga_cards(items, provider, index, is_top10=False):
    """Costruisce le card di una riga (formato componente) e popola home_index.
    Ritorna (cards, primo_hero) — hero = primo item con immagine di sfondo."""
    cards, hero = [], None
    for i, it in enumerate(items):
        if provider == "au":
            uid = f"au:{it['id']}"
            index[uid] = {"provider": "au", "id": it["id"], "slug": it.get("slug"),
                          "name": it.get("name"), "type": "anime",
                          "poster": it.get("poster"), "landscape": it.get("landscape"),
                          "voto": it.get("score"), "year": it.get("year"),
                          "plot": it.get("plot"), "anilist_id": it.get("anilist_id"), "uid": uid}
        else:
            uid = f"sc:{it['id']}"
            index[uid] = {"provider": "sc", "id": it["id"], "slug": it.get("slug"),
                          "name": it.get("name"), "type": it.get("type"),
                          "poster": it.get("poster"), "landscape": it.get("landscape"),
                          "voto": it.get("score"), "year": it.get("year"),
                          "seasons": it.get("seasons"), "uid": uid}
        c = {"uid": uid, "name": it.get("name"), "img": it.get("poster") or it.get("landscape"),
             "type": ("anime" if provider == "au" else it.get("type")),
             "meta": _meta_card(it.get("score"), it.get("year"))}
        if is_top10:
            c["badge"] = str(i + 1)
        cards.append(c)
        if hero is None and it.get("background"):
            hero = {"uid": uid, "name": it.get("name"), "background": it["background"]}
    return cards, hero


def _click_home(clicked, key_last, index, resume_index):
    """Gestisce il click su una card della home (vale per componente veloce e lento)."""
    if not clicked or clicked == st.session_state.get(key_last):
        return
    st.session_state[key_last] = clicked
    uid = str(clicked).split("|")[0]
    if uid in resume_index:                   # "Continua a guardare" -> riprende dal minuto
        riprendi(resume_index[uid])
    elif uid in index:                        # card categoria -> apre la scheda
        st.session_state.sel = index[uid]
        st.session_state.m3u8 = None
        st.session_state.dettaglio_da = "🏠 Home"
        vai("dettaglio")
        st.rerun()


def render_home_netflix():
    """Home in stile Netflix a CARICAMENTO PROGRESSIVO: prima si mostra subito la parte veloce
    (Continua a guardare + caroselli SC), poi — mentre l'utente già esplora — compaiono le righe
    lente (generi + anime). Due componenti separati: Streamlit stremma il primo prima del fetch
    del secondo."""
    index, resume_index, hero = {}, {}, None

    # ---- PARTE VELOCE (subito): Continua a guardare + caroselli SC ----
    rows_fast = []
    cont = _validi(carica_dati().get("recenti", [])[::-1])[:20]
    if cont:
        cc = []
        for it in cont:
            last = it.get("last") or {}
            rk = last.get("resume_key") or it.get("uid")
            resume_index[it["uid"]] = it
            cc.append({"uid": it["uid"], "name": it["name"], "type": it.get("type"),
                       "img": it.get("poster") or it.get("landscape"),
                       "meta": _meta_card(it.get("voto"), it.get("year")),
                       "progress": _progress_frac(rk)})
        rows_fast.append({"label": "Continua a guardare", "items": cc, "continua": True})

    sc_sliders = _home_sliders()
    if not sc_sliders:
        # SC non disponibile in questo momento (dominio in rotazione, rete, ecc.): NON tenere
        # in cache il fallimento -> al prossimo giro ritenta (così l'app si auto-ripara appena
        # SC torna, senza aspettare 10 min o riavviare).
        _home_sliders.clear()
    for label, items in sc_sliders:
        is_top10 = "top 10" in (label or "").lower()
        cards, h = _riga_cards(items, "sc", index, is_top10)
        if hero is None and h:
            hero = h
        rows_fast.append({"label": label, "items": cards})

    if rows_fast:
        clicked = _NETFLIX_HOME(rows=rows_fast, hero=(hero or {}), key="nf_home_fast", default=None)
        _click_home(clicked, "nf_fast_click", index, resume_index)

    # ---- PARTE LENTA (carica mentre esplori): righe per genere + righe anime ----
    extra = _home_extra()
    rows_slow = []
    for label, items in extra.get("generi", []):
        cards, _h = _riga_cards(items, "sc", index)
        rows_slow.append({"label": label, "items": cards})
    for label, items in extra.get("anime", []):
        cards, _h = _riga_cards(items, "au", index)
        rows_slow.append({"label": label, "items": cards})

    st.session_state.home_index = index
    if rows_slow:
        clicked2 = _NETFLIX_HOME(rows=rows_slow, hero={}, key="nf_home_slow", default=None)
        _click_home(clicked2, "nf_slow_click", index, resume_index)
    elif not rows_fast:
        st.info("Categorie non disponibili al momento — usa la **🔍 Cerca**.")


def render_risultati(ris):
    """Risultati di ricerca con lo STESSO template della home: caroselli di locandine
    verticali (nome COMPLETO sotto, a capo); il click apre la scheda (niente bottoni).
    La categoria col match migliore va per prima (anime se cerchi un anime, ecc.)."""
    index = {x["uid"]: x for x in ris}
    tipi = [("🎬 Film", "movie"), ("📺 Serie", "tv"), ("🌸 Anime", "anime")]

    def _primo(tp):                       # posizione del primo risultato di quel tipo
        for i, x in enumerate(ris):       # (ris è già ordinato per pertinenza da cerca_tutto)
            if x.get("type") == tp:
                return i
        return 10 ** 9
    tipi.sort(key=lambda t: _primo(t[1]))  # tipo dominante (match migliore) per primo

    rows_json = []
    for label, tp in tipi:
        items = [x for x in ris if x.get("type") == tp]
        if not items:
            continue
        cards = [{"uid": x["uid"], "name": x.get("name"),
                  "img": x.get("poster") or x.get("landscape"), "type": x.get("type"),
                  "meta": _meta_card(x.get("voto"), x.get("year"))} for x in items]
        rows_json.append({"label": f"{label} ({len(items)})", "items": cards})
    st.session_state.search_index = index
    clicked = _NETFLIX_HOME(rows=rows_json, hero={}, wrap=True, key="nf_search", default=None)
    if clicked and clicked != st.session_state.get("nf_search_click"):
        st.session_state.nf_search_click = clicked
        uid = str(clicked).split("|")[0]
        if uid in index:
            st.session_state.sel = index[uid]
            st.session_state.m3u8 = None
            st.session_state.dettaglio_da = "🔍 Cerca"   # indietro dalla scheda -> torna ai risultati
            vai("dettaglio")
            st.rerun()
# ── Pagina dettaglio in stile Netflix ───────────────────────────────────
_BANNER_HTML = """<!DOCTYPE html><html><head><meta charset="UTF-8"><style>
*{margin:0;box-sizing:border-box}
html,body{overflow:hidden;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Arial,sans-serif}
.b{position:relative;height:330px;border-radius:10px;overflow:hidden;background:#222;background-size:cover;background-position:center 18%}
.g{position:absolute;inset:0;background:linear-gradient(to right,rgba(15,15,15,.95),rgba(15,15,15,.35) 58%,transparent),linear-gradient(to top,#0f0f0f,transparent 62%)}
.i{position:absolute;left:34px;right:34px;bottom:26px;max-width:64%;color:#fff}
.t{font-size:36px;font-weight:800;text-shadow:0 2px 10px #000;line-height:1.05;margin-bottom:8px}
.m{font-size:14px;color:#d2d2d2;font-weight:600;margin-bottom:10px}
.p{font-size:14.5px;line-height:1.5;color:#eaeaea;display:-webkit-box;-webkit-line-clamp:4;-webkit-box-orient:vertical;overflow:hidden}
</style></head><body>
<div class="b" style="background-image:url('__BG__')"><div class="g"></div>
<div class="i"><div class="t">__T__</div><div class="m">__M__</div><div class="p">__P__</div></div></div>
</body></html>"""


def _banner(backdrop, titolo, meta, plot):
    import html as _h
    html = (_BANNER_HTML.replace("__BG__", backdrop or "")
            .replace("__T__", _h.escape(titolo or "")).replace("__M__", _h.escape(meta or ""))
            .replace("__P__", _h.escape(plot or "")))
    components.html(html, height=346)


@st.cache_data(ttl=600, show_spinner=False)
def _dettaglio_sc(tid, slug):
    return sc.dettaglio(tid, slug)


@st.cache_data(ttl=600, show_spinner=False)
def _episodi_sc(tid, slug, stag):
    return sc.episodi(tid, slug, stag)


# ── Rilevamento connessione (modalità offline automatica) ────────────────
def _check_rete():
    for host in ("8.8.8.8", "1.1.1.1"):
        try:
            socket.create_connection((host, 53), timeout=2.5).close()
            return True
        except Exception:
            continue
    return False


@st.cache_data(ttl=15, show_spinner=False)
def _online():
    return _check_rete()


@st.fragment(run_every=8)
def _auto_rete():
    """Solo in offline: controlla se la rete è tornata e in tal caso ripristina l'online."""
    if _check_rete():
        _online.clear()
        st.rerun()


def render_home_offline():
    st.warning("📴 **Modalità offline** — nessuna connessione a internet. "
               "Sono disponibili solo i video **scaricati**. Tornerà online da sola appena c'è rete.")
    if st.button("🔄 Riprova ora"):
        _online.clear(); st.rerun()
    st.markdown("#### 📂 I tuoi video scaricati")
    render_libreria()
    _auto_rete()


# ══════════════════════════════════════════════════════════════════════
#  AGGIORNAMENTO AUTOMATICO
# ══════════════════════════════════════════════════════════════════════
@st.dialog("🎉 Aggiornamento disponibile")
def _popup_aggiornamento(m):
    st.markdown("**TrickFlix %s** è pronta — tu hai la %s."
                % (m.get("versione", "?"), aggiornamenti.versione_locale()))
    note = m.get("note") or []
    if isinstance(note, str):
        note = [note]
    if note:
        st.markdown("\n".join("- " + str(n) for n in note))
    st.caption("Vengono sostituiti solo i file del programma (%d). I video scaricati, "
               "la cronologia e le preferenze restano dove sono."
               % len(aggiornamenti.da_aggiornare(m)))
    c1, c2 = st.columns(2)
    if c2.button("Più tardi", use_container_width=True, key="agg_no"):
        st.session_state.agg_rimandato = True
        st.rerun()
    if c1.button("Aggiorna ora", type="primary", use_container_width=True, key="agg_si"):
        barra = st.progress(0.0, text="Preparo…")
        ok, msg = aggiornamenti.applica(m, lambda f, t: barra.progress(f, text=t))
        if not ok:
            st.error(msg)
        else:
            st.success(msg + "  Riavvio TrickFlix…")
            # il launcher nuovo libera la porta 8501 e quindi spegne questa istanza:
            # la finestra del browser si riconnette da sola al server aggiornato.
            aggiornamenti.riavvia()
            st.stop()


# il controllo gira in un thread: non rallenta l'avvio e se non c'è rete non fa nulla
aggiornamenti.controlla_in_background()
_agg = aggiornamenti.disponibile()
if _agg and st.session_state.vista != "player" and not st.session_state.get("agg_rimandato"):
    _popup_aggiornamento(_agg)      # mai durante la riproduzione: non si interrompe un film


# ══════════════════════════════════════════════════════════════════════
#  HOME
# ══════════════════════════════════════════════════════════════════════
if st.session_state.vista == "home":
    st.markdown("""<style>
.st-key-continua_row [data-testid="stHorizontalBlock"]{flex-wrap:nowrap;overflow-x:auto;overflow-y:hidden;gap:14px;padding-bottom:10px;scrollbar-width:thin}
.st-key-continua_row [data-testid="stColumn"]{min-width:185px;max-width:185px}
.st-key-continua_row [data-testid="stHorizontalBlock"]::-webkit-scrollbar{height:8px}
.st-key-continua_row [data-testid="stHorizontalBlock"]::-webkit-scrollbar-thumb{background:#555;border-radius:4px}
/* download: locandina verticale PICCOLA (non enorme come prima) */
.st-key-dl_lib [data-testid="stImage"] img{width:100%;aspect-ratio:2/3;height:auto;object-fit:cover;border-radius:5px}
</style>""", unsafe_allow_html=True)

    if not _online():
        render_home_offline()
        st.stop()

    st.title("🍿 TrickFlix")
    sezione = st.segmented_control("Sezione", ["🏠 Home", "🔍 Cerca", "📥 Download"],
                                   key="tab_home", label_visibility="collapsed")

    if sezione == "🔍 Cerca":
        with st.form("ricerca"):
            q = st.text_input("Cerca", placeholder="Inception, Tokyo Ghoul, Breaking Bad…",
                              label_visibility="collapsed")
            vai_cerca = st.form_submit_button("🔍 Cerca film, serie e anime", use_container_width=True)
        if vai_cerca and q.strip():
            with st.spinner("Cerco…"):
                st.session_state.risultati = cerca_tutto(q.strip())
            if not st.session_state.risultati:
                st.warning("Nessun risultato. Controlla l'ortografia.")
        ris = st.session_state.risultati
        if ris:
            render_risultati(ris)
    elif sezione == "📥 Download":
        render_download_tab()
    else:                                   # "🏠 Home" (o None)
        render_home_netflix()

    # versione + controllo manuale (quello automatico gira una volta al giorno)
    _v1, _v2 = st.columns([4, 1])
    _v1.caption("TrickFlix v%s" % aggiornamenti.versione_locale())
    if _v2.button("Cerca aggiornamenti", key="agg_manuale", use_container_width=True):
        with st.spinner("Controllo…"):
            aggiornamenti.controlla(forza=True)
        st.session_state.agg_rimandato = False
        if not aggiornamenti.disponibile():
            st.toast("Sei già all'ultima versione.")
        st.rerun()


# ══════════════════════════════════════════════════════════════════════
#  DETTAGLIO
# ══════════════════════════════════════════════════════════════════════
elif st.session_state.vista == "dettaglio":
    m = st.session_state.sel
    if st.button("⬅ Torna"):
        st.session_state.tab_home = st.session_state.get("dettaglio_da", "🏠 Home")
        vai("home"); st.rerun()

    # dati ricchi (trama, backdrop, generi, anno, voto)
    if m.get("provider") == "sc":
        with st.spinner("Carico i dettagli…"):
            d = _dettaglio_sc(m["id"], m["slug"])
    else:
        d = {"name": m["name"], "plot": m.get("plot"), "type": "anime",
             "backdrop": m.get("landscape") or m.get("poster"), "poster": m.get("poster"),
             "year": "", "score": None, "genres": [], "seasons": []}

    meta = "  ·  ".join([x for x in [
        d.get("year"),
        ("⭐ %s" % d["score"]) if d.get("score") else None,
        ("%s min" % d["runtime"]) if d.get("runtime") else None,
        " / ".join(d.get("genres") or []) or None,
    ] if x])
    _banner(d.get("backdrop") or m.get("poster"), d.get("name") or m["name"], meta, d.get("plot"))

    # FILM (SC): solo il tasto Play (la trama è nel banner)
    if m["type"] == "movie":
        if st.button("▶ Guarda ora", type="primary", use_container_width=True):
            with st.spinner("Recupero il flusso…"):
                link = _flusso_sc(m["id"], m.get("slug"))
            riproduci(link, m["name"], m); st.rerun()

    # SERIE (SC): elenco episodi con anteprima + trama + durata
    elif m["type"] == "tv":
        stagioni = d.get("seasons") or sc.stagioni(m["id"], m["slug"]) or [1]
        s_sel = st.selectbox("Stagione", stagioni) if len(stagioni) > 1 else stagioni[0]
        with st.spinner("Carico gli episodi…"):
            eps = _episodi_sc(m["id"], m["slug"], s_sel)
        st.markdown(f"#### Episodi · Stagione {s_sel}")
        for ep in eps:
            with st.container(border=True):
                c1, c2 = st.columns([1, 3])
                if ep.get("image"):
                    c1.image(ep["image"], use_container_width=True)
                with c2:
                    riga = f"**{ep['number']}. {ep.get('name') or 'Episodio ' + str(ep['number'])}**"
                    if ep.get("duration"):
                        riga += f"  ·  {ep['duration']} min"
                    st.markdown(riga)
                    if ep.get("plot"):
                        st.caption(ep["plot"])
                    if st.button("▶ Riproduci", key=f"ep_{s_sel}_{ep['id']}", type="primary"):
                        with st.spinner("Recupero il flusso…"):
                            link = _flusso_sc(m["id"], m.get("slug"), ep["id"], s_sel, ep["number"])
                        ep_ctx = {"id": ep["id"], "season": s_sel, "number": ep["number"]}
                        riproduci(link, f"{m['name']} · S{s_sel}E{ep['number']}", m, ep_ctx); st.rerun()

    # ANIME (AnimeUnity): elenco episodi
    elif m["type"] == "anime":
        base = au_base()
        with st.spinner("Carico gli episodi…"):
            eps = au.episodi(m["id"], m["slug"], base) if base else []
        if not eps:
            st.warning("Episodi non disponibili.")
        else:
            st.markdown(f"#### Episodi ({len(eps)})")
        for i in range(0, len(eps), 6):
            for col, ep in zip(st.columns(6), eps[i:i + 6]):
                if col.button(f"▶ Ep {ep['number']}", key=f"aep_{ep['id']}", use_container_width=True):
                    with st.spinner("Recupero il flusso…"):
                        link = au.m3u8_episodio(ep["id"], base)
                    ep_ctx = {"id": ep["id"], "number": ep["number"]}
                    riproduci(link, f"{m['name']} · Ep {ep['number']}", m, ep_ctx); st.rerun()


# ══════════════════════════════════════════════════════════════════════
#  PLAYER
# ══════════════════════════════════════════════════════════════════════
elif st.session_state.vista == "player":
    offline = st.session_state.get("is_offline", False)
    # il player torna alla scheda solo se ci siamo arrivati da lì; da "Continua a guardare"
    # (o offline, o senza selezione) torna alla home.
    a_home = offline or st.session_state.get("player_torna") == "home" or not st.session_state.get("sel")
    if st.button("⬅ Torna alla home" if a_home else "⬅ Torna ai dettagli"):
        if a_home:
            st.session_state.tab_home = "🏠 Home"
            vai("home")
        else:
            vai("dettaglio")
        st.rerun()
    st.subheader(f"🎬 {st.session_state.titolo_player}" + (" · 📂 offline" if offline else ""))
    # offline = pacchetto HLS locale servito dal ponte -> stesso player hls.js dell'online
    # (i vecchi download .mp4 usano il player nativo: offline_is_file=True)
    # richiesta arrivata dal player (popup episodi / prossimo episodio)
    _pend = st.session_state.get("vai_pendente")
    if _pend:
        st.session_state.vai_pendente = None
        _cambia_episodio(st.session_state.get("play_src"), _pend)
    _az = st.session_state.get("azione_pendente")
    if _az:
        st.session_state.azione_pendente = None
        _esegui_azione(st.session_state.get("play_src"), _az.get("a"), _az.get("d"))

    _src = st.session_state.get("play_src")
    # Episodi per il popup dentro il player (serie/anime online). Sta in cache: si paga
    # una volta sola e poi sfogliare le stagioni mentre guardi non costa nulla.
    _eps_player = []
    if _src and _src.get("type") in ("tv", "anime") and not offline:
        _eps_player = _dati_episodi(_src.get("provider"), _src.get("id"),
                                    _src.get("slug"), _src.get("uid")) or []

    # stato del download di QUESTO video (il tasto nel player cambia messaggio di conseguenza)
    _dl_stato = "mai"                       # "mai" = tasto nascosto (offline: già in locale)
    if _src and not offline:
        _nome_dl = _nome_download(st.session_state.get("titolo_player", ""))
        if dm.file_esiste(_nome_dl + "/master.m3u8"):
            _dl_stato = "fatto"
        elif dm.gia_in_coda(_nome_dl):
            _dl_stato = "coda"
        else:
            _dl_stato = "no"
    # dispositivi per il cast: la ricerca gira in BACKGROUND (costa ~6s), qui si usa
    # l'ultima lista nota. Solo per lo streaming online: la TV non raggiunge il ponte locale.
    _castabile = bool(casting.DISPONIBILE and not offline and st.session_state.get("m3u8"))
    if _castabile:
        casting.scopri_in_background()
    # pref_key = uid della SERIE: lingua/sottotitoli/qualita' scelti qui restano
    # il default per i prossimi episodi della stessa serie.
    mostra_player(st.session_state.m3u8, st.session_state.titolo_player,
                  st.session_state.get("resume_key", ""),
                  is_file=st.session_state.get("offline_is_file", False),
                  pref_key=(_src or {}).get("uid", ""),
                  episodi=_eps_player, ep_corrente=str((_src or {}).get("ep_id") or ""),
                  dl_stato=_dl_stato, cast_dev=(casting.dispositivi() if _castabile else []),
                  cast_scan=(casting.ricerca_in_corso() if _castabile else False),
                  castabile=_castabile)

    if _src and not offline:
        _ascolta_player()      # resta in ascolto delle richieste dal player

    # 📺 Tutti gli episodi (il "prossimo episodio" ora è DENTRO il player, in barra)
    _e_serie = bool(_src and _src.get("type") in ("tv", "anime"))
    _c2 = st.container()
    if _e_serie and _c2.button("📺 Tutti gli episodi", use_container_width=True, key="tutti_ep"):
        # la lista episodi vive nella scheda del titolo: ci si assicura che 'sel' sia
        # proprio questa serie (arrivando da "continua a guardare" potrebbe mancare)
        _sel = st.session_state.get("sel")
        if not _sel or _sel.get("uid") != _src.get("uid"):
            st.session_state.sel = {
                "provider": _src.get("provider"), "id": _src.get("id"), "slug": _src.get("slug"),
                "type": _src.get("type"), "uid": _src.get("uid"), "name": _src.get("name"),
                "poster": _src.get("poster"), "landscape": _src.get("landscape"),
                "anilist_id": _src.get("anilist_id")}
        vai("dettaglio")
        st.rerun()

    # (i tasti download e cast sono ora DENTRO il player, nella barra dei controlli)
