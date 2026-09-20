@echo off
setlocal EnableExtensions
title TrickFlix
cd /d "%~dp0app" 2>nul
if errorlevel 1 goto no_cartella
if not exist "launcher.py" goto no_cartella

echo ============================================================
echo   TrickFlix (Windows)
echo   Cartella: %CD%
echo ============================================================
echo.

set "VENVPY=venv\Scripts\python.exe"
set "PORT_PY=python-portable\python\python.exe"

REM ============================================================
REM  1) L'ambiente esiste gia' ed e' sano?  -> avvia e basta
REM ============================================================
if not exist "%VENVPY%" goto trova_python
"%VENVPY%" -c "import streamlit" >nul 2>&1
if not errorlevel 1 goto avvia
echo Ambiente non valido (o incompleto): lo ricreo da zero...
rmdir /s /q venv 2>nul

REM ============================================================
REM  2) Cerca un Python di sistema utilizzabile.
REM     Ordine: versioni piu' collaudate prima. NON e' una lista rigida:
REM     se l'installazione poi fallisce si passa al Python portatile.
REM ============================================================
:trova_python
set "PY="
for %%v in (3.12 3.13 3.11 3.10 3.14) do call :prova_py "py -%%v"
if not defined PY call :prova_py "python"
if not defined PY call :prova_py "python3"

if not defined PY (
  echo Python non trovato sul computer: lo scarico io ^(versione portatile^).
  echo.
  goto usa_portatile
)

echo Python trovato: %PY%
call :crea_ambiente "%PY%"
if not errorlevel 1 goto avvia
echo.
echo [!] Con il Python del computer l'installazione non e' riuscita.
echo     Probabilmente e' una versione troppo nuova/vecchia per le librerie.
echo     Uso una versione di Python dedicata a TrickFlix.
echo.

REM ============================================================
REM  3) Python PORTATILE: scaricato in app\python-portable\.
REM     Non tocca il sistema, non serve la password, non cambia il
REM     Python che usi per altro. Per rimuoverlo: cancella la cartella.
REM ============================================================
:usa_portatile
if exist "%PORT_PY%" goto portatile_pronto
powershell -NoProfile -ExecutionPolicy Bypass -File "_python_portatile.ps1"
if errorlevel 1 goto no_python
if not exist "%PORT_PY%" goto no_python

:portatile_pronto
rmdir /s /q venv 2>nul
call :crea_ambiente "%PORT_PY%"
if errorlevel 1 goto install_fallita
goto avvia

REM ============================================================
REM  4) Avvio (pythonw = nessuna finestra nera); errori in app_log.txt
REM ============================================================
:avvia
echo.
echo Avvio TrickFlix... l'app si apre tra pochi secondi.
if exist "venv\Scripts\pythonw.exe" (
  start "" "venv\Scripts\pythonw.exe" launcher.py
) else (
  start "" "%VENVPY%" launcher.py
)
REM  piccola pausa (ping invece di timeout: funziona sempre, anche senza console)
ping -n 4 127.0.0.1 >nul 2>&1
exit /b 0

REM ============================================================
REM  Subroutine
REM ============================================================

REM  prova_py "<comando python>" -> se e' un Python 3 funzionante, imposta PY
:prova_py
if defined PY exit /b 0
%~1 -c "import sys; sys.exit(0 if sys.version_info[0]==3 and sys.version_info[1]>=9 else 1)" >nul 2>&1
if errorlevel 1 exit /b 0
set "PY=%~1"
exit /b 0

REM  crea_ambiente "<comando python>" -> crea venv + installa i pacchetti.
REM  Ritorna errorlevel 1 se qualcosa non funziona (cosi' il chiamante puo'
REM  ripiegare sul Python portatile).
:crea_ambiente
echo.
echo ====== PRIMA INSTALLAZIONE - puo' richiedere qualche minuto ======
echo    Non chiudere questa finestra finche' non si apre l'app.
echo.
%~1 -m venv venv
if errorlevel 1 exit /b 1
if not exist "%VENVPY%" exit /b 1
"%VENVPY%" -m pip install --upgrade pip --quiet
"%VENVPY%" -m pip install -r requirements.txt
if errorlevel 1 exit /b 1
REM  verifica VERA: i pacchetti si importano davvero?
"%VENVPY%" -c "import streamlit, requests, Crypto.Cipher, curl_cffi" >nul 2>&1
if errorlevel 1 exit /b 1
REM  segna i requisiti come allineati (stesso marker usato da launcher.py)
"%VENVPY%" -c "import hashlib;open('.deps_ok','w').write(hashlib.sha1(open('requirements.txt','rb').read()).hexdigest())" >nul 2>&1
exit /b 0

REM ============================================================
REM  Errori
REM ============================================================
:no_cartella
echo [!] File del progetto mancanti.
echo     Tieni TrickFlix.bat nella cartella principale, accanto alla cartella "app".
echo.
pause
exit /b 1

:no_python
echo.
echo [!] Non sono riuscito a scaricare Python automaticamente.
echo     Controlla la connessione a internet e riprova.
echo     In alternativa installa Python da https://www.python.org/downloads/
echo.
pause
exit /b 1

:install_fallita
echo.
echo [!] Installazione delle librerie non riuscita.
echo     1^) Controlla la connessione a internet e riprova.
echo     2^) Se la cartella TrickFlix e' dentro percorsi molto lunghi
echo        ^(tante sottocartelle^), spostala piu' in alto - per esempio in
echo        C:\TrickFlix - e riprova: Windows ha un limite sulla lunghezza
echo        dei percorsi che manda in errore alcune librerie.
echo.
pause
exit /b 1
