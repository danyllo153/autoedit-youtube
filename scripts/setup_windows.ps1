<#
.SYNOPSIS
  Prepara o Windows para o autoedit: ferramentas (winget) + dependencias Python.
  Rode dentro da pasta do repositorio:  .\scripts\setup_windows.ps1
  Pode rodar de novo sem problema (pula o que ja esta instalado).
#>
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

function Tem($nome) { [bool](Get-Command $nome -ErrorAction SilentlyContinue) }

# 1) ferramentas de sistema
if (-not (Tem "yt-dlp")) { winget install -e --id yt-dlp.yt-dlp }
if (-not (Tem "ffmpeg")) { winget install -e --id Gyan.FFmpeg }
if (-not (Tem "deno"))   { winget install -e --id DenoLand.Deno }   # o yt-dlp usa para resolver o YouTube

# 2) Python: use o lancador "py". O comando "python" pode ser o atalho da Microsoft Store (nao roda nada).
if (-not (Tem "py")) {
    Write-Host "Python nao encontrado. Instale com:  winget install Python.Python.3.12  e rode de novo." -ForegroundColor Yellow
    exit 1
}
py -m pip install --upgrade pip
py -m pip install -r requirements.txt -r requirements-ocr.txt -r requirements-visao.txt -r requirements-animacao.txt
py -m playwright install chromium   # navegador da animacao HTML (scripts\animar_html.py), ~150 MB

Write-Host "`nPronto. Se acabou de instalar algo, FECHE e abra o PowerShell (o PATH so atualiza em janela nova)." -ForegroundColor Green
Write-Host "Vigia da fila de videos:  py scripts\watch_fila.py"
