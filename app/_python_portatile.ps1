# ============================================================
#  TrickFlix - scarica un Python PORTATILE per Windows
#  (equivalente di scarica_python_portatile() in TrickFlix.command per macOS)
#
#  Serve quando sul PC non c'e' Python, oppure c'e' una versione con cui le
#  dipendenze non si installano (a ogni nuova release di Python i pacchetti
#  compilati - pyarrow/numpy/pycryptodome - restano indietro per qualche mese).
#
#  Fonte: python-build-standalone di Astral (gli autori di ruff/uv), release
#  ufficiali su GitHub. Non installa nulla nel sistema, non serve la password:
#  estrae un Python dentro app\python-portable\ e basta cancellare la cartella.
#
#  Stampa in output il percorso di python.exe (ultima riga) oppure esce con 1.
# ============================================================
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'   # niente barra di progresso lenta

$base = Split-Path -Parent $MyInvocation.MyCommand.Path
$dest = Join-Path $base 'python-portable'
$exe = Join-Path $dest 'python\python.exe'

# gia' scaricato in un tentativo precedente? riusalo
if (Test-Path $exe) {
    Write-Host "Python portatile gia' presente."
    exit 0
}

# Versioni preferite: le piu' "mature" lato pacchetti compilati (wheel gia'
# pubblicati per tutto). Si prende la prima disponibile nella release.
$preferite = @('3.12', '3.13', '3.11')
$arch = if ($env:PROCESSOR_ARCHITECTURE -eq 'ARM64') { 'aarch64' } else { 'x86_64' }

Write-Host "Cerco la versione piu' adatta di Python..."
$rel = Invoke-RestMethod -Uri 'https://api.github.com/repos/astral-sh/python-build-standalone/releases/latest' `
                         -Headers @{ 'User-Agent' = 'TrickFlix' } -TimeoutSec 60

$asset = $null
foreach ($v in $preferite) {
    $asset = $rel.assets | Where-Object {
        $_.name -like "cpython-$v.*-$arch-pc-windows-msvc-install_only.tar.gz"
    } | Select-Object -First 1
    if ($asset) { break }
}
if (-not $asset) {
    Write-Host "[!] Nessun pacchetto Python compatibile trovato."
    exit 1
}

New-Item -ItemType Directory -Force -Path $dest | Out-Null
$tgz = Join-Path $dest 'py.tar.gz'
$mb = [math]::Round($asset.size / 1MB)
Write-Host "Scarico Python ($mb MB, una volta sola)..."

# curl.exe e tar.exe sono nativi in Windows 10/11 (System32)
& curl.exe -fL $asset.browser_download_url -o $tgz --silent --show-error
if ($LASTEXITCODE -ne 0 -or -not (Test-Path $tgz)) {
    Write-Host "[!] Download non riuscito (connessione?)."
    exit 1
}

Write-Host "Estraggo..."
& tar.exe -xzf $tgz -C $dest
Remove-Item $tgz -Force -ErrorAction SilentlyContinue

if (-not (Test-Path $exe)) {
    Write-Host "[!] Estrazione non riuscita."
    exit 1
}
Write-Host "Python pronto (solo per TrickFlix, il sistema non e' stato toccato)."
exit 0
