#!/usr/bin/env bash
# Prepara uma sessão Linux (ex.: Claude Code na nuvem) para editar vídeos com o autoedit.
# Idempotente: pode rodar de novo sem problema.  Uso:  ./scripts/setup_sessao.sh
# No Windows use:  scripts\setup_windows.ps1
set -euo pipefail
cd "$(dirname "$0")/.."

SUDO=""
[ "$(id -u)" != "0" ] && command -v sudo >/dev/null 2>&1 && SUDO="sudo"

# 1) ffmpeg / ffprobe (sistema)
if ! command -v ffmpeg >/dev/null 2>&1 || ! command -v ffprobe >/dev/null 2>&1; then
  echo "[setup] instalando ffmpeg..."
  $SUDO apt-get update -qq && $SUDO apt-get install -y -qq ffmpeg
fi

# 2) dependências Python do projeto (requirements.txt é a fonte da verdade)
echo "[setup] instalando dependências Python..."
python3 -m pip install -q --disable-pip-version-check -r requirements.txt -r requirements-ocr.txt -r requirements-visao.txt

# 3) yt-dlp: só para baixar links. Na nuvem o YouTube bloqueia o download (anti-robô);
#    o download real roda no PC do usuário (scripts/baixar_video.ps1 / scripts/watch_fila.py).
python3 -m pip install -q --disable-pip-version-check yt-dlp

# 4) conferência
echo "[setup] versões:"
ffmpeg -version | head -1
python3 - <<'EOF'
import importlib
for mod in ("scenedetect", "faster_whisper", "av", "PIL", "numpy", "cv2", "yt_dlp", "rapidocr_onnxruntime"):
    try:
        m = importlib.import_module(mod)
        print(f"  ok  {mod} {getattr(m, '__version__', '')}")
    except Exception as e:
        print(f"  FALTA {mod}: {e}")
EOF
echo "[setup] pronto. Teste rápido:  ./scripts/make_test_footage.sh && python autoedit.py test_footage/gameplay_test.mp4 --target 80 --extras on --shorts"
