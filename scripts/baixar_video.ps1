<#
.SYNOPSIS
  Baixa um video (ou so a legenda) do YouTube para usar como material no autoedit.

.EXAMPLE
  .\scripts\baixar_video.ps1 https://youtu.be/WuzMxEKJHkQ
  .\scripts\baixar_video.ps1 https://youtu.be/WuzMxEKJHkQ -Altura 480
  .\scripts\baixar_video.ps1 https://youtu.be/WuzMxEKJHkQ -SoLegenda
  .\scripts\baixar_video.ps1 https://youtu.be/WuzMxEKJHkQ -Navegador chrome

  Use so com video seu ou que voce tenha direito de usar.
#>
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string]$Url,

    # Pasta de saida. Padrao: Documentos\Autoedit do OneDrive; se nao existir, Downloads.
    [string]$Saida = "",

    # Altura maxima do video (720 = arquivo menor, suficiente para analise).
    [int]$Altura = 720,

    # Baixa so a legenda automatica (.srt), sem o video.
    [switch]$SoLegenda,

    # Navegador com sessao do YouTube, se aparecer "Sign in to confirm you're not a bot".
    # Os cookies ficam no seu PC. Valores: chrome, edge, firefox, brave...
    [string]$Navegador = ""
)

$ErrorActionPreference = "Stop"

# --- pasta de saida (sem caminho fixo: usa o perfil de quem roda) ---
if (-not $Saida) {
    $onedrive = Join-Path $env:USERPROFILE "OneDrive\Documentos\Autoedit"
    $Saida = if (Test-Path (Split-Path $onedrive -Parent)) { $onedrive } else { Join-Path $env:USERPROFILE "Downloads" }
}
New-Item -ItemType Directory -Force -Path $Saida | Out-Null

# --- dependencias ---
if (-not (Get-Command yt-dlp -ErrorAction SilentlyContinue)) {
    Write-Host "yt-dlp nao encontrado. Instale com:  winget install yt-dlp.yt-dlp" -ForegroundColor Yellow
    exit 1
}
if (-not $SoLegenda -and -not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
    Write-Host "ffmpeg nao encontrado (precisa dele para juntar video e audio). Instale com:  winget install Gyan.FFmpeg" -ForegroundColor Yellow
    Write-Host "Depois feche e abra o PowerShell." -ForegroundColor Yellow
    exit 1
}

# --- argumentos do yt-dlp ---
$modelo = Join-Path $Saida "video_referencia.%(ext)s"
$ytArgs = @("--no-playlist", "--restrict-filenames")

if ($Navegador) { $ytArgs += @("--cookies-from-browser", $Navegador) }

if ($SoLegenda) {
    $modelo = Join-Path $Saida "legenda"
    $ytArgs += @("--skip-download", "--write-auto-subs", "--write-subs",
                 "--sub-langs", "pt.*,en.*", "--convert-subs", "srt")
} else {
    $ytArgs += @("-f", "bv*[height<=$Altura]+ba/b[height<=$Altura]",
                 "--merge-output-format", "mp4")
}

$ytArgs += @("-o", $modelo, $Url)

Write-Host "Salvando em: $Saida" -ForegroundColor Cyan
& yt-dlp @ytArgs
if ($LASTEXITCODE -ne 0) {
    Write-Host "Falhou. Se foi 'Sign in to confirm you're not a bot', rode de novo com:  -Navegador chrome" -ForegroundColor Yellow
    exit $LASTEXITCODE
}

Write-Host "`nPronto. Arquivos em: $Saida" -ForegroundColor Green
Get-ChildItem $Saida | Sort-Object LastWriteTime -Descending | Select-Object -First 5 Name, @{n="MB";e={[math]::Round($_.Length/1MB,1)}}
