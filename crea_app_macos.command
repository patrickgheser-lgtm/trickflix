#!/bin/bash
# ============================================================
#  TrickFlix - crea "TrickFlix.app" (+ .dmg opzionale) per macOS
# ------------------------------------------------------------
#  ESEGUILO UNA VOLTA SOLA, DAL TERMINALE (così Gatekeeper non lo blocca):
#     1) apri Terminale
#     2) scrivi:  bash        (con uno spazio dopo)
#     3) TRASCINA questo file (crea_app_macos.command) nella finestra del Terminale
#     4) premi Invio
#  Crea un VERO .app (via osacompile) dentro questa cartella: da quel momento basta
#  fare DOPPIO CLICK su TrickFlix.app. La prima volta macOS dirà che non può
#  verificarlo -> Impostazioni > Privacy e sicurezza > "Apri comunque" (UNA volta).
#  L'app, una volta autorizzata, si toglie da sola la quarantena dai file.
# ============================================================
set -e
cd "$(dirname "$0")"
PROJ="$(pwd)"
APP="$PROJ/TrickFlix.app"

command -v osacompile >/dev/null 2>&1 || { echo "[!] osacompile non trovato: esegui su macOS."; exit 1; }

echo "Creo $APP ..."
rm -rf "$APP" "$PROJ/launcher.applescript"

# --- AppleScript: trova la cartella del progetto (genitore del .app), toglie la quarantena,
#     poi avvia. Prima installazione -> apre il Terminale col progresso (script collaudato);
#     avvii successivi -> silenzioso in background. ---
cat > "$PROJ/launcher.applescript" <<'APPLESCRIPT'
on run
	set appPath to POSIX path of (path to me)
	set projPath to do shell script "p=" & quoted form of appPath & "; dirname \"${p%/}\""
	do shell script "/usr/bin/xattr -dr com.apple.quarantine " & quoted form of projPath & " >/dev/null 2>&1; true"
	set venvPy to projPath & "/app/venv/bin/python"
	set hasVenv to (do shell script "if [ -x " & quoted form of venvPy & " ]; then echo yes; else echo no; fi")
	if hasVenv is "yes" then
		-- distacco COMPLETO (subshell + redirect di stdin/stdout/stderr): così "do shell script"
		-- ritorna subito, l'applet termina e NON resta nel dock (niente force-quit per riavviare).
		do shell script "cd " & quoted form of (projPath & "/app") & " && ( nohup " & quoted form of venvPy & " " & quoted form of (projPath & "/app/launcher.py") & " >/dev/null 2>&1 </dev/null & )"
	else
		tell application "Terminal"
			activate
			do script "bash " & quoted form of (projPath & "/TrickFlix.command")
		end tell
	end if
end run
APPLESCRIPT

osacompile -o "$APP" "$PROJ/launcher.applescript"
rm -f "$PROJ/launcher.applescript"

# --- icona del .app: un .icns DENTRO il bundle (sopravvive a zip/unzip). Cerca TrickFlix.icns
#     in app/ (consigliato) o in radice. osacompile usa "applet.icns" -> lo sovrascriviamo. ---
ICNS=""
[ -f "$PROJ/app/TrickFlix.icns" ] && ICNS="$PROJ/app/TrickFlix.icns"
[ -z "$ICNS" ] && [ -f "$PROJ/TrickFlix.icns" ] && ICNS="$PROJ/TrickFlix.icns"
if [ -n "$ICNS" ]; then
  cp "$ICNS" "$APP/Contents/Resources/applet.icns"
  touch "$APP"                       # forza il Finder a rinfrescare l'icona
  echo "Icona applicata al .app."
else
  echo "(Nessuna icona personalizzata: metti app/TrickFlix.icns per averla. Uso quella di default.)"
fi

# --- firma ad-hoc (niente account Apple) ---
codesign --force --deep --timestamp=none -s - "$APP" >/dev/null 2>&1 || true
echo "Firma ad-hoc applicata."

echo
echo "FATTO -> creato TrickFlix.app in questa cartella."
echo "Ora fai DOPPIO CLICK su TrickFlix.app."
echo "La prima volta: Impostazioni di sistema > Privacy e sicurezza > 'Apri comunque' (una volta sola)."
echo

# --- .dmg opzionale per distribuire ad altri (contiene la cartella col .app dentro) ---
printf "Creo anche un .dmg per distribuirlo ad altri? [s/N] "
read -r RISP
if [ "$RISP" = "s" ] || [ "$RISP" = "S" ]; then
  STAGEBASE="$(mktemp -d)"
  STAGE="$STAGEBASE/TrickFlix"
  mkdir -p "$STAGE"
  rsync -a \
    --exclude venv --exclude python-portable --exclude Download --exclude __pycache__ \
    --exclude .chrome_profile --exclude .git --exclude .claude --exclude dati.json \
    --exclude posizioni.json --exclude app_log.txt --exclude domini_cache.json --exclude '*.dmg' \
    "$PROJ/" "$STAGE/"
  rm -f "$PROJ/TrickFlix.dmg"
  hdiutil create -volname "TrickFlix" -srcfolder "$STAGEBASE" -ov -format UDZO "$PROJ/TrickFlix.dmg"
  rm -rf "$STAGEBASE"
  echo "Creato TrickFlix.dmg (cartella TrickFlix con dentro l'app)."
fi
