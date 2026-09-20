#!/bin/bash
# ============================================================
#  TrickFlix - avvio su macOS (doppio click)
#  Trova/installa Python, crea l'ambiente, installa tutto, avvia l'app.
# ============================================================
cd "$(dirname "$0")/app" || exit 1
clear
echo "============================================================"
echo "  TrickFlix (macOS)"
echo "  Cartella: $(pwd)"
echo "============================================================"
echo

# --- I file del progetto ci sono? ---
if [ ! -f "launcher.py" ]; then
  echo "[!] File del progetto mancanti in questa cartella."
  echo "    Avvia TrickFlix.command dentro la cartella completa"
  echo "    (devono esserci launcher.py, app.py, requirements.txt)."
  read -r -p "Premi Invio per chiudere..."
  exit 1
fi

# --- Trova un Python 3 adatto (3.9 - 3.13) ---
trova_python() {
  for c in python3.12 python3.11 python3.13 python3.10 python3 python3.9; do
    if command -v "$c" >/dev/null 2>&1; then
      v=$("$c" -c 'import sys;print(sys.version_info[0]*100+sys.version_info[1])' 2>/dev/null)
      if [ -n "$v" ] && [ "$v" -ge 309 ] && [ "$v" -lt 314 ]; then
        echo "$c"; return 0
      fi
    fi
  done
  return 1
}

# --- Scarica un Python PORTATILE (python-build-standalone) se manca quello di sistema:
#     niente password admin, niente Homebrew, niente download manuale da python.org. ---
PORT_PY="python-portable/python/bin/python3"
scarica_python_portatile() {
  local arch pya pat url
  arch="$(uname -m)"
  if [ "$arch" = "arm64" ]; then pya="aarch64"; else pya="x86_64"; fi
  pat='https://[^"]*cpython-3\.1[0-3][^"]*-'"$pya"'-apple-darwin-install_only\.tar\.gz'
  url="$(curl -fsSL "https://api.github.com/repos/astral-sh/python-build-standalone/releases/latest" 2>/dev/null | grep -oE "$pat" | head -1)"
  [ -z "$url" ] && return 1
  echo "Scarico Python portatile (~40MB, una volta sola)..."
  rm -rf python-portable; mkdir -p python-portable
  curl -fL "$url" -o python-portable/py.tar.gz || return 1
  tar -xzf python-portable/py.tar.gz -C python-portable || return 1
  rm -f python-portable/py.tar.gz
  [ -x "$PORT_PY" ]
}

PY="$(trova_python)"
[ -z "$PY" ] && [ -x "$PORT_PY" ] && PY="$(pwd)/$PORT_PY"   # portatile gia' scaricato
if [ -z "$PY" ]; then
  echo "[!] Python 3 non trovato: lo installo automaticamente (versione portatile)."
  if scarica_python_portatile; then
    PY="$(pwd)/$PORT_PY"
  fi
fi
if [ -z "$PY" ]; then
  echo "Download automatico non riuscito; provo altri metodi."
  if command -v brew >/dev/null 2>&1; then
    echo "Homebrew trovato: provo a installare Python 3.12 (puo' chiedere la password)..."
    brew install python@3.12
    PY="$(trova_python)"
  fi
  if [ -z "$PY" ]; then
    echo "Apro la pagina ufficiale di Python per macOS."
    echo "Scarica 'macOS 64-bit universal2 installer', installalo,"
    echo "poi riapri TrickFlix (doppio click)."
    open "https://www.python.org/downloads/macos/" 2>/dev/null
    read -r -p "Premi Invio per chiudere..."
    exit 1
  fi
fi
echo "Python trovato: $PY ($("$PY" --version 2>&1))"

# --- Ambiente copiato da un altro computer? non e' valido: ricrea ---
if [ -f "venv/bin/python" ]; then
  if ! venv/bin/python --version >/dev/null 2>&1; then
    echo "Ambiente non valido per questo Mac: lo ricreo da zero..."
    rm -rf venv
  fi
fi

# --- Prima installazione (solo se l'ambiente non esiste) ---
if [ ! -f "venv/bin/python" ]; then
  [ -d venv ] && rm -rf venv   # es. venv creato su Windows e copiato qui
  echo
  echo "====== PRIMA INSTALLAZIONE - puo' richiedere qualche minuto ======"
  echo "   Non chiudere questa finestra finche' non si apre l'app."
  echo
  "$PY" -m venv venv || { echo "[!] Creazione ambiente virtuale fallita."; read -r -p "Invio per chiudere..."; exit 1; }
  venv/bin/python -m pip install --upgrade pip
  venv/bin/python -m pip install -r requirements.txt || {
    echo "[!] Installazione dipendenze fallita. Controlla la connessione e riprova."
    read -r -p "Invio per chiudere..."; exit 1
  }
fi

# --- Ambiente GIA' esistente: se requirements.txt e' cambiato (nuova dipendenza aggiunta,
#     es. curl_cffi) la installo ora. Marker .deps_ok = sha1 di requirements.txt, lo stesso
#     usato da launcher.py -> non si installa due volte. ---
if [ -f "venv/bin/python" ] && [ -f "requirements.txt" ]; then
  firma="$(shasum requirements.txt 2>/dev/null | awk '{print $1}')"
  if [ -n "$firma" ] && [ "$firma" != "$(cat .deps_ok 2>/dev/null)" ]; then
    echo "Nuove dipendenze rilevate: le installo (una volta sola)..."
    if venv/bin/python -m pip install -r requirements.txt; then
      printf '%s' "$firma" > .deps_ok
    fi
  fi
fi

echo
echo "Avvio TrickFlix... l'app si apre nel browser tra pochi secondi."

# Avvio in background: sopravvive alla chiusura del Terminale (come pythonw su Windows).
# Eventuali errori finiscono in app_log.txt.
nohup venv/bin/python launcher.py >/dev/null 2>&1 &
sleep 2

# Chiudi DA SOLA questa finestra del Terminale (l'app gira gia' in background): identifica
# la propria finestra tramite il tty, cosi' non tocca altre finestre. Parte dopo l'uscita
# dello script (finestra inattiva) -> niente prompt "processo in esecuzione".
TTY="$(tty 2>/dev/null || true)"
case "$TTY" in
  /dev/*)
    ( sleep 1
      osascript -e "tell application \"Terminal\"
repeat with w in windows
try
if tty of selected tab of w is \"$TTY\" then close w
end try
end repeat
end tell" >/dev/null 2>&1
    ) </dev/null >/dev/null 2>&1 &
    ;;
esac
exit 0
