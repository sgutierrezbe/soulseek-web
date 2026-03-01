# ──────────────────────────────────────────────────────────────────────────────
#  soulseek-web — instalador para Windows (TOTALMENTE AUTÓNOMO)
#  Instala slskd (daemon Soulseek) + soulseek-web en un solo paso.
#  Ejecutar en PowerShell:
#    Set-ExecutionPolicy Bypass -Scope Process -Force
#    .\install.ps1
#
#  O desde internet (una sola línea):
#    Set-ExecutionPolicy Bypass -Scope Process -Force; irm https://raw.githubusercontent.com/sgutierrezbe/soulseek-web/main/install.ps1 | iex
# ──────────────────────────────────────────────────────────────────────────────

$ErrorActionPreference = "Stop"

$INSTALL_DIR    = "$env:LOCALAPPDATA\soulseek-web"
$SLSKD_DIR      = "$env:LOCALAPPDATA\slskd"
$SLSKD_CONFIG   = "$SLSKD_DIR\slskd.yml"
$MUSIC_DIR      = "$env:USERPROFILE\Music\Soulseek Downloads"
$REPO           = "https://github.com/sgutierrezbe/soulseek-web.git"
$PORT           = 8080
$SLSKD_PORT     = 5030

# ── Helpers ───────────────────────────────────────────────────────────────────

function Write-Step  { param($msg) Write-Host "`n→ $msg" -ForegroundColor Cyan }
function Write-Ok    { param($msg) Write-Host "  ✓ $msg" -ForegroundColor Green }
function Write-Warn  { param($msg) Write-Host "  ⚠ $msg" -ForegroundColor Yellow }
function Write-Fail  { param($msg) Write-Host "`n  ✗ $msg`n" -ForegroundColor Red; exit 1 }

function Test-CommandExists { param($cmd) return [bool](Get-Command $cmd -ErrorAction SilentlyContinue) }

function New-RandomApiKey {
    return ([System.Guid]::NewGuid().ToString("N") + [System.Guid]::NewGuid().ToString("N"))
}

# ── Banner ────────────────────────────────────────────────────────────────────

Write-Host ""
Write-Host "  ╔══════════════════════════════════════════════════╗" -ForegroundColor Green
Write-Host "  ║         SLSK//WEB  —  Windows                   ║" -ForegroundColor Green
Write-Host "  ║   Soulseek completo en tu PC, sin configurar    ║" -ForegroundColor Green
Write-Host "  ╚══════════════════════════════════════════════════╝" -ForegroundColor Green
Write-Host ""

# ── Verificar Python ──────────────────────────────────────────────────────────

Write-Step "Verificando Python 3.11+..."

$python = $null
foreach ($cmd in @("python", "python3", "py")) {
    if (Test-CommandExists $cmd) {
        $ver = & $cmd --version 2>&1
        if ($ver -match "(\d+)\.(\d+)") {
            if ([int]$Matches[1] -gt 3 -or ([int]$Matches[1] -eq 3 -and [int]$Matches[2] -ge 11)) {
                $python = $cmd
                Write-Ok "$ver"
                break
            }
        }
    }
}

if (-not $python) {
    Write-Warn "Python 3.11+ no encontrado. Intentando instalar con winget..."
    if (Test-CommandExists "winget") {
        winget install --id Python.Python.3.12 -e --accept-source-agreements --accept-package-agreements
        $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
        foreach ($cmd in @("python", "py")) {
            if (Test-CommandExists $cmd) { $python = $cmd; break }
        }
    }
    if (-not $python) {
        Write-Host ""
        Write-Host "  Descargá Python desde: https://www.python.org/downloads/" -ForegroundColor Yellow
        Write-Host "  ⚠ Marcá 'Add Python to PATH' durante la instalación." -ForegroundColor Yellow
        Write-Fail "Instalá Python 3.11+ y volvé a ejecutar este script."
    }
    Write-Ok "Python instalado"
}

# ── Verificar Git ─────────────────────────────────────────────────────────────

Write-Step "Verificando Git..."

if (-not (Test-CommandExists "git")) {
    Write-Warn "Git no encontrado. Instalando con winget..."
    if (Test-CommandExists "winget") {
        winget install --id Git.Git -e --accept-source-agreements --accept-package-agreements
        $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
    }
    if (-not (Test-CommandExists "git")) {
        Write-Host "  Descargalo desde: https://git-scm.com/download/win" -ForegroundColor Yellow
        Write-Fail "Instalá Git y volvé a ejecutar este script."
    }
}
Write-Ok "$(git --version)"

# ── Descargar slskd ───────────────────────────────────────────────────────────

Write-Step "Descargando slskd (daemon de Soulseek)..."

New-Item -ItemType Directory -Force -Path $SLSKD_DIR | Out-Null

$slskdExe = "$SLSKD_DIR\slskd.exe"
$needsDownload = $true

if (Test-Path $slskdExe) {
    Write-Ok "slskd ya instalado, omitiendo descarga"
    $needsDownload = $false
}

if ($needsDownload) {
    try {
        $release  = Invoke-RestMethod "https://api.github.com/repos/slskd/slskd/releases/latest" -TimeoutSec 15
        $asset    = $release.assets | Where-Object { $_.name -match "win-x64\.zip$" } | Select-Object -First 1
        if (-not $asset) { Write-Fail "No se encontró el binario win-x64 en la última release de slskd." }

        $zipPath  = "$env:TEMP\slskd.zip"
        Write-Host "  Descargando $($asset.name)..." -ForegroundColor Gray
        Invoke-WebRequest -Uri $asset.browser_download_url -OutFile $zipPath -UseBasicParsing

        Expand-Archive -Path $zipPath -DestinationPath $SLSKD_DIR -Force
        Remove-Item $zipPath -ErrorAction SilentlyContinue

        # El zip puede tener una subcarpeta; mover el exe a $SLSKD_DIR raíz
        $foundExe = Get-ChildItem "$SLSKD_DIR" -Recurse -Filter "slskd.exe" | Select-Object -First 1
        if ($foundExe -and $foundExe.FullName -ne $slskdExe) {
            Move-Item $foundExe.FullName $slskdExe -Force
        }
        Write-Ok "slskd $($release.tag_name) descargado"
    } catch {
        Write-Fail "No se pudo descargar slskd: $_`n  Intentalo manualmente desde https://github.com/slskd/slskd/releases"
    }
}

# ── Generar API key y escribir config inicial de slskd ───────────────────────

Write-Step "Configurando slskd..."

# Generar API key sólo si no existe ya una config
$apiKey = $null
if (Test-Path $SLSKD_CONFIG) {
    # Intentar leer la key existente para no regenerarla
    $existingContent = Get-Content $SLSKD_CONFIG -Raw -ErrorAction SilentlyContinue
    if ($existingContent -match 'key:\s*"([a-f0-9]{64})"') {
        $apiKey = $Matches[1]
        Write-Ok "Reutilizando API key existente"
    }
}

if (-not $apiKey) {
    $apiKey = New-RandomApiKey
    Write-Ok "API key generada"
}

# Config mínima: sin credenciales de Soulseek todavía (las pide el wizard)
$musicFwd       = $MUSIC_DIR.Replace("\", "/")
$incompleteFwd  = "$musicFwd/.incomplete"

$slskdYml = @"
# Configuración inicial generada por soulseek-web
# Las credenciales de Soulseek se configuran desde el wizard del navegador.

soulseek:
  username: ""
  password: ""

web:
  port: $SLSKD_PORT
  authentication:
    disabled: false
    api_keys:
      - name: soulseek-web
        key: "$apiKey"

directories:
  downloads: "$musicFwd"
  incomplete: "$incompleteFwd"

shares:
  directories: []
"@

New-Item -ItemType Directory -Force -Path (Split-Path $MUSIC_DIR) | Out-Null
New-Item -ItemType Directory -Force -Path $MUSIC_DIR | Out-Null
Set-Content -Path $SLSKD_CONFIG -Value $slskdYml -Encoding UTF8
Write-Ok "slskd.yml escrito"

# ── Guardar local_setup.json para que soulseek-web sepa que está en modo local ─

$localSetup = @{
    local              = $true
    slskd_url          = "http://localhost:$SLSKD_PORT"
    slskd_api_key      = $apiKey
    slskd_config_path  = $SLSKD_CONFIG
    slskd_exe_path     = $slskdExe
    default_music_path = $MUSIC_DIR
} | ConvertTo-Json
# Written after cloning the repo, see below

# ── Clonar o actualizar soulseek-web ─────────────────────────────────────────

Write-Step "Instalando soulseek-web en $INSTALL_DIR ..."

if (Test-Path "$INSTALL_DIR\.git") {
    Push-Location $INSTALL_DIR
    & git pull --quiet
    Pop-Location
    Write-Ok "Repositorio actualizado"
} else {
    if (Test-Path $INSTALL_DIR) { Remove-Item $INSTALL_DIR -Recurse -Force }
    & git clone --quiet $REPO $INSTALL_DIR
    Write-Ok "Repositorio clonado"
}

Set-Location $INSTALL_DIR

# Escribir local_setup.json ahora que la carpeta existe
Set-Content -Path "$INSTALL_DIR\local_setup.json" -Value $localSetup -Encoding UTF8
Write-Ok "local_setup.json escrito"

# ── Entorno virtual y dependencias Python ────────────────────────────────────

Write-Step "Instalando dependencias Python..."

& $python -m venv venv
& ".\venv\Scripts\python.exe" -m pip install --quiet --upgrade pip
& ".\venv\Scripts\pip.exe" install --quiet -r requirements.txt
Write-Ok "Dependencias instaladas"

# ── Crear start.bat ───────────────────────────────────────────────────────────

Write-Step "Creando acceso directo..."

$bat = @"
@echo off
title Soulseek Web
cd /d "$INSTALL_DIR"
echo.
echo  SLSK//WEB corriendo en http://localhost:$PORT
echo  Cerra esta ventana para detenerlo.
echo.
start "" /b "$slskdExe" --config "$SLSKD_CONFIG"
timeout /t 3 /nobreak >nul
start "" "http://localhost:$PORT"
call venv\Scripts\uvicorn.exe main:app --host 0.0.0.0 --port $PORT
"@
Set-Content -Path "$INSTALL_DIR\start.bat" -Value $bat -Encoding ASCII

# Acceso directo en el escritorio
$WshShell = New-Object -ComObject WScript.Shell
$desktop  = [System.Environment]::GetFolderPath("Desktop")
$lnk      = $WshShell.CreateShortcut("$desktop\Soulseek Web.lnk")
$lnk.TargetPath       = "$INSTALL_DIR\start.bat"
$lnk.WorkingDirectory = $INSTALL_DIR
$lnk.Description      = "Iniciar Soulseek Web"
$lnk.Save()
Write-Ok "Acceso directo creado en el escritorio"

# ── Primera ejecución ─────────────────────────────────────────────────────────

Write-Step "Iniciando slskd y soulseek-web por primera vez..."

Start-Process -FilePath $slskdExe -ArgumentList "--config `"$SLSKD_CONFIG`"" -WindowStyle Hidden
Start-Sleep -Seconds 2
Start-Process -FilePath "$INSTALL_DIR\start.bat" -WindowStyle Normal

# ── Resultado ─────────────────────────────────────────────────────────────────

Write-Host ""
Write-Host "  ╔══════════════════════════════════════════════════════════════╗" -ForegroundColor Green
Write-Host "  ║   ✓  ¡Todo listo! slskd + soulseek-web instalados          ║" -ForegroundColor Green
Write-Host "  ╚══════════════════════════════════════════════════════════════╝" -ForegroundColor Green
Write-Host ""
Write-Host "  Abrí el navegador en:" -ForegroundColor White
Write-Host "      http://localhost:$PORT" -ForegroundColor Yellow
Write-Host ""
Write-Host "  Solo te va a pedir tu usuario y contraseña de Soulseek." -ForegroundColor White
Write-Host "  (Si no tenés cuenta, creá una gratis en https://www.slsknet.org/)" -ForegroundColor Gray
Write-Host ""
Write-Host "  Para iniciar la próxima vez, doble clic en 'Soulseek Web' en el escritorio." -ForegroundColor White
Write-Host ""
